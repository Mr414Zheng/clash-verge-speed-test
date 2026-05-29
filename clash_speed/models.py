"""Domain models for proxy test results."""

from dataclasses import dataclass


@dataclass
class NodeResult:
    name: str
    group: str
    latency_ms: int | None = None
    speed_mbps: float | None = None
    error: str | None = None
    risk_level: str | None = None
