"""
Clash Verge Proxy Speed Tester

Tests latency and download speed of all proxy nodes exposed by a local
Clash Verge instance via its REST API.

Usage:
    python clash_speed_test.py
    python clash_speed_test.py --secret YOUR_SECRET
    python clash_speed_test.py --secret YOUR_SECRET --sort speed --workers 5
"""

import argparse
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Callable, Iterator
from urllib.parse import urlparse

import requests

# ---------------------------------------------------------------------------
# Try rich for pretty output; fall back to plain text table
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.table import Table

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_API_URL = "http://127.0.0.1:9097"
DEFAULT_LATENCY_URL = "http://www.gstatic.com/generate_204"
DEFAULT_SPEED_URL = "http://speedtest.tele2.net/1MB.zip"
FALLBACK_SPEED_URLS = [
    "http://speedtest.tele2.net/10MB.zip",
    "http://proof.ovh.net/files/10Mb.dat",
]
DEFAULT_TIMEOUT = 10  # seconds
DEFAULT_SPEED_TIMEOUT = 15  # seconds per speed-test download attempt
DEFAULT_SPEED_DURATION = 5  # seconds to read bytes for each speed-test attempt
DEFAULT_LATENCY_TIMEOUT = 5000  # ms (Clash API expects milliseconds)
DEFAULT_WORKERS = 3
# Common mixed-port / port values to probe when the API does not expose it.
PROXY_PORT_FALLBACKS = [7890, 7891, 9090]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class NodeResult:
    name: str
    group: str
    latency_ms: int | None = None
    speed_mbps: float | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Clash API client
# ---------------------------------------------------------------------------
class ClashClient:
    """Thin wrapper around the Clash Verge REST API."""

    def __init__(
        self,
        api_url: str,
        secret: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        if secret:
            self.session.headers["Authorization"] = f"Bearer {secret}"

    # -- Proxies -------------------------------------------------------------
    def get_proxies(self) -> dict:
        """Return the raw /proxies JSON payload."""
        resp = self.session.get(
            f"{self.api_url}/proxies", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def list_proxy_names(self) -> list[tuple[str, str]]:
        """Return [(group_name, proxy_name), ...] for all leaf proxies.

        Only Selector-type groups are considered.  When a proxy appears in
        multiple Selector groups the first occurrence wins (order-stable).
        """
        data = self.get_proxies()
        proxies_section = data.get("proxies", {})

        # Collect (group, name) pairs only from selectable group types,
        # tracking each group's type so we can prefer pure Selector groups.
        raw: list[tuple[str, str]] = []
        group_type: dict[str, str] = {}
        for group_name, group_info in proxies_section.items():
            gtype = (group_info.get("type") or "").lower()
            group_type[group_name] = gtype
            # Only groups whose *type* is "Selector" can be switched via
            # the PUT /proxies/{group} API.  Skip everything else.
            # Also skip the GLOBAL meta-group which cannot be switched.
            if gtype != "selector" or group_name.upper() == "GLOBAL":
                continue
            members = group_info.get("all") or group_info.get("now") or []
            if isinstance(members, str):
                members = [members]
            for member in members:
                raw.append((group_name, member))

        # Deduplicate by proxy name, keeping first occurrence (already
        # limited to Selector groups above).
        seen: set[str] = set()
        deduped: list[tuple[str, str]] = []
        for group, name in raw:
            if name not in seen:
                seen.add(name)
                deduped.append((group, name))
        return deduped

    # -- Latency test --------------------------------------------------------
    def test_latency(
        self, proxy_name: str, url: str = DEFAULT_LATENCY_URL
    ) -> int | None:
        """Return latency in ms for *proxy_name*, or None on failure."""
        encoded = requests.utils.quote(proxy_name, safe="")
        resp = self.session.get(
            f"{self.api_url}/proxies/{encoded}/delay",
            params={"timeout": DEFAULT_LATENCY_TIMEOUT, "url": url},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("delay")

    # -- Download speed test -------------------------------------------------
    def test_download_speed(self, proxy_name: str, url: str) -> float:
        """Download *url* through *proxy_name* and return speed in Mbps.

        If the primary *url* fails, tries each URL in FALLBACK_SPEED_URLS
        until one succeeds.  Raises only if all URLs fail.
        """
        proxy_url = f"http://127.0.0.1:{self.get_proxy_port()}"
        proxies = {"http": proxy_url, "https": proxy_url}

        urls_to_try = [url] + [u for u in FALLBACK_SPEED_URLS if u != url]
        failures: list[str] = []
        for try_url in urls_to_try:
            try:
                return self._download_and_measure(try_url, proxies)
            except Exception as exc:
                failures.append(f"{try_url}: {exc}")
                continue
        raise RuntimeError(
            "all speed test URLs failed: " + "; ".join(failures)
        )

    # -- Config --------------------------------------------------------------
    def get_configs(self) -> dict:
        """Return the raw /configs JSON payload."""
        resp = self.session.get(
            f"{self.api_url}/configs", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_proxy_port(self) -> int:
        """Return the HTTP proxy port to use for speed tests.

        Resolution order:
        1. Explicitly set ``_proxy_port`` (from ``--proxy-port`` CLI arg).
        2. ``mixed-port`` from ``GET /configs``.
        3. First reachable port among :data:`PROXY_PORT_FALLBACKS`.
        4. Last resort: the REST API port itself.
        """
        if getattr(self, "_proxy_port", None) is not None:
            return self._proxy_port  # type: ignore[return-value]

        # Try reading mixed-port from the Clash config API.
        try:
            cfg = self.get_configs()
            mixed = cfg.get("mixed-port") or cfg.get("mixed_port")
            if mixed:
                return int(mixed)
        except Exception:
            pass

        # Probe fallback ports.
        for port in PROXY_PORT_FALLBACKS:
            try:
                resp = requests.head(
                    f"http://127.0.0.1:{port}",
                    timeout=2,
                )
                # Even a non-200 response means a server is listening.
                if resp.status_code:
                    return port
            except Exception:
                continue

        # Absolute fallback: API port (may not work, but it's the last option).
        return urlparse(self.api_url).port or 9097

    def _download_and_measure(self, url: str, proxies: dict) -> float:
        """Download *url* through the given *proxies* dict; return Mbps."""
        state: dict[str, object] = {
            "total_bytes": 0,
            "error": None,
            "resp": None,
            "finished": False,
            "first_byte_at": None,
        }
        state_lock = threading.Lock()
        stop_download = threading.Event()
        first_byte_received = threading.Event()
        download_finished = threading.Event()

        def _download_worker() -> None:
            resp: requests.Response | None = None
            try:
                resp = requests.get(
                    url,
                    proxies=proxies,
                    timeout=DEFAULT_SPEED_TIMEOUT,
                    stream=True,
                )
                with state_lock:
                    state["resp"] = resp
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=1024):
                    if stop_download.is_set():
                        break
                    if not chunk:
                        continue
                    with state_lock:
                        if state["first_byte_at"] is None:
                            state["first_byte_at"] = time.monotonic()
                        state["total_bytes"] = int(state["total_bytes"]) + len(chunk)
                    first_byte_received.set()
            except Exception as exc:
                with state_lock:
                    state["error"] = exc
            finally:
                if resp is not None:
                    resp.close()
                with state_lock:
                    state["finished"] = True
                download_finished.set()

        worker = threading.Thread(target=_download_worker, daemon=True)
        worker.start()

        wait_deadline = time.monotonic() + DEFAULT_SPEED_TIMEOUT
        while (
            not first_byte_received.is_set()
            and not download_finished.is_set()
            and time.monotonic() < wait_deadline
        ):
            time.sleep(0.01)

        with state_lock:
            total_bytes = int(state["total_bytes"])
            error = state["error"]
            resp = state["resp"]
            finished = bool(state["finished"])
            first_byte_at = state["first_byte_at"]

        if not first_byte_received.is_set():
            if not finished:
                stop_download.set()
                if resp is not None:
                    threading.Thread(target=resp.close, daemon=True).start()
                raise requests.Timeout(
                    f"speed test timed out before receiving body bytes after "
                    f"{DEFAULT_SPEED_TIMEOUT} seconds"
                )
            if total_bytes == 0 and error is not None:
                raise error  # type: ignore[misc]
            raise ValueError("speed test URL returned no body bytes")

        measurement_start = (
            float(first_byte_at)
            if first_byte_at is not None
            else time.monotonic()
        )
        remaining = max(
            0.0,
            DEFAULT_SPEED_DURATION - (time.monotonic() - measurement_start),
        )
        worker.join(remaining)

        with state_lock:
            total_bytes = int(state["total_bytes"])
            error = state["error"]
            resp = state["resp"]
            finished = bool(state["finished"])

        if not finished:
            stop_download.set()
            if resp is not None:
                threading.Thread(target=resp.close, daemon=True).start()
            if total_bytes == 0:
                raise requests.Timeout(
                    f"speed test timed out before receiving body bytes after "
                    f"{DEFAULT_SPEED_DURATION} seconds"
                )

        if total_bytes == 0 and error is not None:
            raise error  # type: ignore[misc]

        if total_bytes == 0:
            raise ValueError("speed test URL returned no body bytes")

        elapsed = min(time.monotonic() - measurement_start, DEFAULT_SPEED_DURATION)
        if elapsed == 0:
            elapsed = 0.001
        mbps = (total_bytes * 8) / (elapsed * 1_000_000)  # megabits per second
        return round(mbps, 2)

    def select_proxy(self, group_name: str, proxy_name: str) -> None:
        """Switch *group_name* to use *proxy_name*."""
        encoded_group = requests.utils.quote(group_name, safe="")
        resp = self.session.put(
            f"{self.api_url}/proxies/{encoded_group}",
            json={"name": proxy_name},
            timeout=self.timeout,
        )
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Speed test runner
# ---------------------------------------------------------------------------
StopChecker = Callable[[], bool]


def _is_stop_requested(stop_requested: StopChecker | None) -> bool:
    return bool(stop_requested and stop_requested())


def iter_latency_tests(
    client: ClashClient,
    proxies: list[tuple[str, str]],
    latency_url: str,
    workers: int = 1,
    stop_requested: StopChecker | None = None,
) -> Iterator[tuple[str, tuple[int | None, str | None]]]:
    """Yield latency results as each proxy finishes.

    The optional *stop_requested* callback prevents new queued tests from being
    submitted. Already-running requests are allowed to finish so partial results
    remain valid.
    """

    def _test_one(name: str) -> tuple[str, tuple[int | None, str | None]]:
        try:
            delay = client.test_latency(name, url=latency_url)
            return name, (delay, None)
        except Exception as exc:
            return name, (None, f"latency error: {exc}")

    if workers <= 1:
        for _group, name in proxies:
            if _is_stop_requested(stop_requested):
                break
            yield _test_one(name)
        return

    proxy_iter = iter(proxies)
    max_workers = max(1, workers)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}

        def _submit_next() -> bool:
            if _is_stop_requested(stop_requested):
                return False
            try:
                _group, next_name = next(proxy_iter)
            except StopIteration:
                return False
            futures[pool.submit(_test_one, next_name)] = next_name
            return True

        for _ in range(min(max_workers, len(proxies))):
            if not _submit_next():
                break

        while futures:
            done, _pending = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                futures.pop(future, None)
                yield future.result()
                if not _is_stop_requested(stop_requested):
                    _submit_next()


def run_latency_tests(
    client: ClashClient,
    proxies: list[tuple[str, str]],
    latency_url: str,
    workers: int = 1,
) -> dict[str, tuple[int | None, str | None]]:
    """Test latency for every proxy.

    When *workers* > 1, tests run concurrently via ThreadPoolExecutor.

    Returns {proxy_name: (latency_ms_or_None, error_or_None)}.
    """
    results: dict[str, tuple[int | None, str | None]] = {}
    for name, result in iter_latency_tests(client, proxies, latency_url, workers):
        results[name] = result

    return results


def iter_speed_tests(
    client: ClashClient,
    proxies: list[tuple[str, str]],
    speed_url: str,
    workers: int,
    stop_requested: StopChecker | None = None,
) -> Iterator[tuple[str, tuple[float | None, str | None]]]:
    """Yield speed results as each proxy finishes.

    Proxies in the same group still run sequentially because selecting a proxy
    mutates group state. Groups run concurrently up to *workers* threads.
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    for group, name in proxies:
        grouped[group].append(name)

    result_queue: Queue[tuple[str, tuple[float | None, str | None]]] = Queue()

    def _test_group(group: str, names: list[str]) -> None:
        for name in names:
            if _is_stop_requested(stop_requested):
                break
            try:
                client.select_proxy(group, name)
                speed = client.test_download_speed(name, speed_url)
                result_queue.put((name, (speed, None)))
            except Exception as exc:
                result_queue.put((name, (None, f"speed error: {exc}")))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(_test_group, group, names) for group, names in grouped.items()]
        pending = set(futures)

        while pending:
            try:
                yield result_queue.get(timeout=0.1)
            except Empty:
                pass

            done = {future for future in pending if future.done()}
            for future in done:
                pending.remove(future)
                future.result()

        while True:
            try:
                yield result_queue.get_nowait()
            except Empty:
                break


def run_speed_tests(
    client: ClashClient,
    proxies: list[tuple[str, str]],
    speed_url: str,
    workers: int,
) -> dict[str, tuple[float | None, str | None]]:
    """Test download speed for every proxy.

    Tests for proxies within the same group are serialised (select_proxy
    mutates global proxy state for that group).  Different groups run
    concurrently up to *workers* threads.

    Returns {proxy_name: (speed_mbps_or_None, error_or_None)}.
    """
    results: dict[str, tuple[float | None, str | None]] = {}
    for name, result in iter_speed_tests(client, proxies, speed_url, workers):
        results[name] = result
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def print_results(
    results: list[NodeResult],
    sort_by: str = "latency",
) -> None:
    """Pretty-print results using rich or plain text."""

    # Sort
    if sort_by == "speed":
        results.sort(
            key=lambda r: (
                r.speed_mbps is None,
                -(r.speed_mbps or 0),
            )
        )
    else:  # latency
        results.sort(
            key=lambda r: (
                r.latency_ms is None,
                r.latency_ms or 999_999,
            )
        )

    if HAS_RICH:
        try:
            _print_rich(results)
        except (UnicodeEncodeError, UnicodeDecodeError):
            # Rich console itself may fail on some terminals; fall back.
            _print_plain(results)
    else:
        _print_plain(results)


def _print_rich(results: list[NodeResult]) -> None:
    console = Console()
    table = Table(title="Clash Verge Proxy Speed Test Results")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Proxy", style="cyan", no_wrap=True)
    table.add_column("Group", style="magenta")
    table.add_column("Latency (ms)", justify="right")
    table.add_column("Speed (Mbps)", justify="right")
    table.add_column("Error", style="red")

    for idx, r in enumerate(results, 1):
        lat = str(r.latency_ms) if r.latency_ms is not None else "-"
        spd = f"{r.speed_mbps:.2f}" if r.speed_mbps is not None else "-"
        err = r.error or ""
        table.add_row(str(idx), r.name, r.group, lat, spd, err)

    console.print(table)


def _print_plain(results: list[NodeResult]) -> None:
    header = f"{'#':>4}  {'Proxy':<30} {'Group':<20} {'Latency(ms)':>12} {'Speed(Mbps)':>12}  {'Error'}"
    print(header)
    print("-" * len(header))
    for idx, r in enumerate(results, 1):
        lat = str(r.latency_ms) if r.latency_ms is not None else "-"
        spd = f"{r.speed_mbps:.2f}" if r.speed_mbps is not None else "-"
        err = r.error or ""
        print(f"{idx:>4}  {r.name:<30} {r.group:<20} {lat:>12} {spd:>12}  {err}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test latency and download speed of Clash Verge proxy nodes."
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Clash Verge REST API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--secret",
        default="",
        help="Clash API secret (Bearer token)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--latency-url",
        default=DEFAULT_LATENCY_URL,
        help=f"URL used for latency tests (default: {DEFAULT_LATENCY_URL})",
    )
    parser.add_argument(
        "--speed-url",
        default=DEFAULT_SPEED_URL,
        help=f"URL used for download speed tests (default: {DEFAULT_SPEED_URL})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Concurrent download workers (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--sort",
        choices=["latency", "speed"],
        default="latency",
        help="Sort results by latency or speed (default: latency)",
    )
    parser.add_argument(
        "--skip-speed",
        action="store_true",
        help="Skip download speed tests (latency only)",
    )
    parser.add_argument(
        "--proxy-port",
        type=int,
        default=None,
        help=(
            "HTTP proxy port for speed tests (default: auto-detect from "
            "Clash API mixed-port, then probe 7890/7891/9090)"
        ),
    )
    return parser.parse_args()


def main() -> None:
    # Fix UnicodeEncodeError on Windows GBK consoles (flag emoji etc.)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(errors="replace")
        except Exception:
            pass

    args = parse_args()

    client = ClashClient(
        api_url=args.api_url,
        secret=args.secret,
        timeout=args.timeout,
    )

    # Apply explicit proxy-port override (if any) before any speed tests.
    if args.proxy_port is not None:
        client._proxy_port = args.proxy_port

    # 1. Fetch proxies
    print("Fetching proxy list from Clash Verge...")
    try:
        proxies = client.list_proxy_names()
    except requests.ConnectionError:
        print(
            f"ERROR: Cannot connect to Clash Verge at {args.api_url}. "
            "Is it running?",
            file=sys.stderr,
        )
        sys.exit(1)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status == 401:
            print(
                "ERROR: Unauthorized (401). Clash API requires a secret, "
                "or the --secret value is incorrect.",
                file=sys.stderr,
            )
        else:
            print(f"ERROR: API returned an error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not proxies:
        print("No proxies found. Check your subscription or API URL.")
        sys.exit(0)

    print(f"Found {len(proxies)} proxy node(s).")

    # 2. Latency tests
    print("Running latency tests...")
    latency_map = run_latency_tests(client, proxies, args.latency_url)

    # 3. Speed tests (optional)
    speed_map: dict[str, tuple[float | None, str | None]] = {}
    if not args.skip_speed:
        proxy_port = client.get_proxy_port()
        print(
            f"Running download speed tests with {args.workers} worker(s) "
            f"(proxy port {proxy_port})..."
        )
        speed_map = run_speed_tests(client, proxies, args.speed_url, args.workers)
    else:
        print("Skipping download speed tests (--skip-speed).")

    # 4. Build result rows
    results: list[NodeResult] = []
    for group, name in proxies:
        lat, lat_err = latency_map.get(name, (None, None))
        spd, spd_err = speed_map.get(name, (None, None))

        errors: list[str] = []
        if lat_err:
            errors.append(lat_err)
        if spd_err:
            errors.append(spd_err)

        node = NodeResult(
            name=name,
            group=group,
            latency_ms=lat,
            speed_mbps=spd,
            error="; ".join(errors) if errors else None,
        )
        results.append(node)

    # 5. Print
    print()
    print_results(results, sort_by=args.sort)


if __name__ == "__main__":
    main()
