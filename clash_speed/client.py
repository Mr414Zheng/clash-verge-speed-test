"""Clash Verge REST API client and proxy-port resolution."""

from urllib.parse import urlparse

import requests

from .defaults import (
    DEFAULT_LATENCY_TIMEOUT,
    DEFAULT_LATENCY_URL,
    DEFAULT_TIMEOUT,
    PROXY_PORT_FALLBACKS,
)


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

    def get_proxies(self) -> dict:
        """Return the raw /proxies JSON payload."""
        resp = self.session.get(
            f"{self.api_url}/proxies", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def list_proxy_names(self) -> list[tuple[str, str]]:
        """Return [(group_name, proxy_name), ...] for all leaf proxies.

        Only Selector-type groups are considered. When a proxy appears in
        multiple Selector groups the first occurrence wins (order-stable).
        """
        data = self.get_proxies()
        proxies_section = data.get("proxies", {})

        # Only Selector groups can be switched; GLOBAL must also be excluded.
        raw: list[tuple[str, str]] = []
        for group_name, group_info in proxies_section.items():
            gtype = (group_info.get("type") or "").lower()
            if gtype != "selector" or group_name.upper() == "GLOBAL":
                continue
            members = group_info.get("all") or group_info.get("now") or []
            if isinstance(members, str):
                members = [members]
            for member in members:
                raw.append((group_name, member))

        seen: set[str] = set()
        deduped: list[tuple[str, str]] = []
        for group, name in raw:
            if name not in seen:
                seen.add(name)
                deduped.append((group, name))
        return deduped

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

    def test_download_speed(self, proxy_name: str, url: str) -> float:
        """Download *url* through *proxy_name* and return speed in Mbps."""
        from .speed import test_download_speed

        return test_download_speed(self, proxy_name, url)

    def _download_and_measure(self, url: str, proxies: dict) -> float:
        """Compatibility wrapper for the historical private helper."""
        from .speed import download_and_measure

        return download_and_measure(url, proxies)

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

        try:
            cfg = self.get_configs()
            mixed = cfg.get("mixed-port") or cfg.get("mixed_port")
            if mixed:
                return int(mixed)
        except Exception:
            pass

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

        return urlparse(self.api_url).port or 9097

    def select_proxy(self, group_name: str, proxy_name: str) -> None:
        """Switch *group_name* to use *proxy_name*."""
        encoded_group = requests.utils.quote(group_name, safe="")
        resp = self.session.put(
            f"{self.api_url}/proxies/{encoded_group}",
            json={"name": proxy_name},
            timeout=self.timeout,
        )
        resp.raise_for_status()
