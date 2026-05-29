"""Latency and speed-test orchestration."""

from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from queue import Empty, Queue
import threading
from typing import Callable, Iterator, Protocol

from .risk import fetch_risk_level

StopChecker = Callable[[], bool]
SpeedResult = tuple[float | None, str | None, str | None]


class TestClient(Protocol):
    def test_latency(self, proxy_name: str, url: str) -> int | None:
        ...

    def get_selected_proxies(self, group_names: list[str]) -> dict[str, str]:
        ...

    def select_proxy(self, group_name: str, proxy_name: str) -> None:
        ...

    def test_download_speed(self, proxy_name: str, url: str) -> float:
        ...

    def get_proxy_port(self) -> int:
        ...


def _is_stop_requested(stop_requested: StopChecker | None) -> bool:
    return bool(stop_requested and stop_requested())


def _snapshot_selected(
    client: TestClient, groups: list[str]
) -> dict[str, str]:
    """Capture selector state before speed tests mutate group selections."""
    if not groups:
        return {}
    selected = client.get_selected_proxies(groups)
    missing = [group for group in groups if group not in selected]
    if missing:
        raise RuntimeError(
            "could not capture current selected proxy for group(s): "
            + ", ".join(missing)
        )
    return selected


def _restore_selected(
    client: TestClient, selected_by_group: dict[str, str]
) -> None:
    """Best-effort restore for groups whose original selection was captured."""
    for group, selected in selected_by_group.items():
        try:
            client.select_proxy(group, selected)
        except Exception:
            continue


def _combine_errors(errors: list[str]) -> str | None:
    return "; ".join(errors) if errors else None


def _test_selected_speed_and_risk(
    client: TestClient,
    proxy_name: str,
    speed_url: str,
) -> SpeedResult:
    """Run selected-node speed and risk requests in the same selection window."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        speed_future = pool.submit(
            client.test_download_speed,
            proxy_name,
            speed_url,
        )
        risk_future = pool.submit(fetch_risk_level, client)

        speed: float | None
        risk_level: str | None
        errors: list[str] = []

        try:
            speed = speed_future.result()
        except Exception as exc:
            speed = None
            errors.append(f"speed error: {exc}")

        try:
            risk_level = risk_future.result()
        except Exception as exc:
            risk_level = None
            errors.append(f"risk error: {exc}")

    return speed, risk_level, _combine_errors(errors)


def iter_latency_tests(
    client: TestClient,
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
    client: TestClient,
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
    client: TestClient,
    proxies: list[tuple[str, str]],
    speed_url: str,
    workers: int,
    stop_requested: StopChecker | None = None,
) -> Iterator[tuple[str, SpeedResult]]:
    """Yield speed results as each proxy finishes.

    Proxies in the same group still run sequentially because selecting a proxy
    mutates group state. Groups run concurrently up to *workers* threads.
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    for group, name in proxies:
        grouped[group].append(name)

    selected_before = _snapshot_selected(client, list(grouped))
    result_queue: Queue[tuple[str, SpeedResult]] = Queue()
    force_stop = threading.Event()

    def _should_stop() -> bool:
        return force_stop.is_set() or _is_stop_requested(stop_requested)

    def _test_group(group: str, names: list[str]) -> None:
        for name in names:
            if _should_stop():
                break
            try:
                client.select_proxy(group, name)
                result_queue.put((
                    name,
                    _test_selected_speed_and_risk(client, name, speed_url),
                ))
            except Exception as exc:
                result_queue.put((name, (None, None, f"speed error: {exc}")))

    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    futures = [
        pool.submit(_test_group, group, names)
        for group, names in grouped.items()
    ]
    pending = set(futures)
    try:
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
    finally:
        force_stop.set()
        for future in pending:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        _restore_selected(client, selected_before)


def run_speed_tests(
    client: TestClient,
    proxies: list[tuple[str, str]],
    speed_url: str,
    workers: int,
) -> dict[str, SpeedResult]:
    """Test download speed for every proxy.

    Tests for proxies within the same group are serialised (select_proxy
    mutates global proxy state for that group). Different groups run
    concurrently up to *workers* threads.

    Returns {proxy_name: (speed_mbps_or_None, risk_level_or_None, error_or_None)}.
    """
    results: dict[str, SpeedResult] = {}
    for name, result in iter_speed_tests(client, proxies, speed_url, workers):
        results[name] = result
    return results
