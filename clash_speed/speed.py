"""HTTP proxy download speed measurement."""

import threading
import time
from typing import Protocol

import requests

from .defaults import (
    DEFAULT_SPEED_DURATION,
    DEFAULT_SPEED_TIMEOUT,
    FALLBACK_SPEED_URLS,
)


class SpeedClient(Protocol):
    def get_proxy_port(self) -> int:
        ...


def build_proxy_config(client: SpeedClient) -> dict[str, str]:
    """Return requests proxy config for the active local Clash HTTP proxy."""
    proxy_url = f"http://127.0.0.1:{client.get_proxy_port()}"
    return {"http": proxy_url, "https": proxy_url}


def test_download_speed(client: SpeedClient, proxy_name: str, url: str) -> float:
    """Download *url* through *proxy_name* and return speed in Mbps.

    If the primary *url* fails, tries each URL in FALLBACK_SPEED_URLS until one
    succeeds. Raises only if all URLs fail.
    """
    del proxy_name
    proxies = build_proxy_config(client)

    urls_to_try = [url] + [u for u in FALLBACK_SPEED_URLS if u != url]
    failures: list[str] = []
    measure = getattr(client, "_download_and_measure", download_and_measure)
    for try_url in urls_to_try:
        try:
            return measure(try_url, proxies)
        except Exception as exc:
            failures.append(f"{try_url}: {exc}")
            continue
    raise RuntimeError(
        "all speed test URLs failed: " + "; ".join(failures)
    )


def download_and_measure(url: str, proxies: dict) -> float:
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
    mbps = (total_bytes * 8) / (elapsed * 1_000_000)
    return round(mbps, 2)
