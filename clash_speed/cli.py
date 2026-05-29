"""Command-line entrypoint and terminal output."""

import argparse
import sys

import requests

from .client import ClashClient
from .defaults import (
    DEFAULT_API_URL,
    DEFAULT_LATENCY_URL,
    DEFAULT_SPEED_URL,
    DEFAULT_TIMEOUT,
    DEFAULT_WORKERS,
)
from .models import NodeResult
from .runners import run_latency_tests, run_speed_tests

try:
    from rich.console import Console
    from rich.table import Table

    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def print_results(
    results: list[NodeResult],
    sort_by: str = "latency",
) -> None:
    """Pretty-print results using rich or plain text."""
    if sort_by == "speed":
        results.sort(
            key=lambda r: (
                r.speed_mbps is None,
                -(r.speed_mbps or 0),
            )
        )
    else:
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
    table.add_column("Risk", justify="center")
    table.add_column("Error", style="red")

    for idx, r in enumerate(results, 1):
        lat = str(r.latency_ms) if r.latency_ms is not None else "-"
        spd = f"{r.speed_mbps:.2f}" if r.speed_mbps is not None else "-"
        risk = r.risk_level or "-"
        err = r.error or ""
        table.add_row(str(idx), r.name, r.group, lat, spd, risk, err)

    console.print(table)


def _print_plain(results: list[NodeResult]) -> None:
    header = (
        f"{'#':>4}  {'Proxy':<30} {'Group':<20} {'Latency(ms)':>12} "
        f"{'Speed(Mbps)':>12} {'Risk':>10}  {'Error'}"
    )
    print(header)
    print("-" * len(header))
    for idx, r in enumerate(results, 1):
        lat = str(r.latency_ms) if r.latency_ms is not None else "-"
        spd = f"{r.speed_mbps:.2f}" if r.speed_mbps is not None else "-"
        risk = r.risk_level or "-"
        err = r.error or ""
        print(
            f"{idx:>4}  {r.name:<30} {r.group:<20} {lat:>12} "
            f"{spd:>12} {risk:>10}  {err}"
        )


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

    if args.proxy_port is not None:
        client._proxy_port = args.proxy_port

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

    print("Running latency tests...")
    latency_map = run_latency_tests(client, proxies, args.latency_url)

    speed_map: dict[str, tuple[float | None, str | None, str | None]] = {}
    if not args.skip_speed:
        proxy_port = client.get_proxy_port()
        print(
            f"Running download speed tests with {args.workers} worker(s) "
            f"(proxy port {proxy_port})..."
        )
        speed_map = run_speed_tests(client, proxies, args.speed_url, args.workers)
    else:
        print("Skipping download speed tests (--skip-speed).")

    results: list[NodeResult] = []
    for group, name in proxies:
        lat, lat_err = latency_map.get(name, (None, None))
        spd, risk, spd_err = speed_map.get(name, (None, None, None))

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
            risk_level=risk,
            error="; ".join(errors) if errors else None,
        )
        results.append(node)

    print()
    print_results(results, sort_by=args.sort)
