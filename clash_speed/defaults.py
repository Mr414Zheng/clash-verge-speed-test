"""Default configuration values shared by the CLI, UI, and runners."""

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
