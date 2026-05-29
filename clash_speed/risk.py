"""Risk-level lookup through the active Clash HTTP proxy."""

from typing import Protocol

import requests

from .defaults import DEFAULT_TIMEOUT
from .speed import build_proxy_config

ANALYZE_IP_URL = "https://getgpt.pro/api/analyze-ip"
ANALYZE_IP_HEADERS = {
    "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
    "Accept": "*/*",
}


class RiskClient(Protocol):
    def get_proxy_port(self) -> int:
        ...


def fetch_risk_level(
    client: RiskClient,
    url: str = ANALYZE_IP_URL,
    timeout: int | None = None,
) -> str | None:
    """Fetch riskLevel through the currently selected Clash proxy path."""
    proxies = build_proxy_config(client)
    request_timeout = (
        timeout
        if timeout is not None
        else getattr(client, "timeout", DEFAULT_TIMEOUT)
    )
    resp = requests.get(
        url,
        headers=ANALYZE_IP_HEADERS,
        proxies=proxies,
        timeout=request_timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return parse_risk_level(data)


def parse_risk_level(data: object) -> str | None:
    """Extract riskLevel from common analyze-ip response shapes."""
    if not isinstance(data, dict):
        return None

    value = data.get("riskLevel")
    if value is None and isinstance(data.get("data"), dict):
        value = data["data"].get("riskLevel")

    if value is None:
        return None
    text = str(value).strip()
    return text or None
