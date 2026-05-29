"""Public API for the Clash Verge speed tester package."""

from .client import ClashClient
from .defaults import (
    DEFAULT_API_URL,
    DEFAULT_LATENCY_TIMEOUT,
    DEFAULT_LATENCY_URL,
    DEFAULT_SPEED_DURATION,
    DEFAULT_SPEED_TIMEOUT,
    DEFAULT_SPEED_URL,
    DEFAULT_TIMEOUT,
    DEFAULT_WORKERS,
    FALLBACK_SPEED_URLS,
    PROXY_PORT_FALLBACKS,
)
from .models import NodeResult
from .results import build_display_data, results_to_csv, sort_results
from .runners import (
    StopChecker,
    iter_latency_tests,
    iter_speed_tests,
    run_latency_tests,
    run_speed_tests,
)

__all__ = [
    "ClashClient",
    "DEFAULT_API_URL",
    "DEFAULT_LATENCY_TIMEOUT",
    "DEFAULT_LATENCY_URL",
    "DEFAULT_SPEED_DURATION",
    "DEFAULT_SPEED_TIMEOUT",
    "DEFAULT_SPEED_URL",
    "DEFAULT_TIMEOUT",
    "DEFAULT_WORKERS",
    "FALLBACK_SPEED_URLS",
    "NodeResult",
    "PROXY_PORT_FALLBACKS",
    "StopChecker",
    "build_display_data",
    "iter_latency_tests",
    "iter_speed_tests",
    "results_to_csv",
    "run_latency_tests",
    "run_speed_tests",
    "sort_results",
]
