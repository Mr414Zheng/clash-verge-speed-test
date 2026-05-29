"""Latency and speed-test orchestration."""

from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from queue import Empty, Queue
from typing import Callable, Iterator, Protocol

StopChecker = Callable[[], bool]


class TestClient(Protocol):
    def test_latency(self, proxy_name: str, url: str) -> int | None:
        ...

    def select_proxy(self, group_name: str, proxy_name: str) -> None:
        ...

    def test_download_speed(self, proxy_name: str, url: str) -> float:
        ...


def _is_stop_requested(stop_requested: StopChecker | None) -> bool:
    return bool(stop_requested and stop_requested())


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
    client: TestClient,
    proxies: list[tuple[str, str]],
    speed_url: str,
    workers: int,
) -> dict[str, tuple[float | None, str | None]]:
    """Test download speed for every proxy.

    Tests for proxies within the same group are serialised (select_proxy
    mutates global proxy state for that group). Different groups run
    concurrently up to *workers* threads.

    Returns {proxy_name: (speed_mbps_or_None, error_or_None)}.
    """
    results: dict[str, tuple[float | None, str | None]] = {}
    for name, result in iter_speed_tests(client, proxies, speed_url, workers):
        results[name] = result
    return results
