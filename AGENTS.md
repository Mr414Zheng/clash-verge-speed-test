# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Clash Verge proxy node speed tester. Connects to a local Clash Verge REST API to discover proxy nodes, test latency (via API), and test download speed (via HTTP proxy). Two interfaces: CLI script and Streamlit web UI.

## Commands

```bash
# CLI usage
python clash_speed_test.py --secret YOUR_SECRET
python clash_speed_test.py --secret YOUR_SECRET --skip-speed
python clash_speed_test.py --secret YOUR_SECRET --sort speed --workers 3

# Streamlit web UI
streamlit run app.py

# Install dependencies
pip install -r requirements.txt

# Syntax check
python -c "import py_compile; py_compile.compile('clash_speed_test.py', doraise=True)"
python -c "import py_compile; py_compile.compile('app.py', doraise=True)"
```

## Architecture

- **`clash_speed/`** — Core package. Contains defaults, `NodeResult`, `ClashClient`, HTTP speed measurement, latency/speed runners, pure result conversion helpers, and CLI output/argument handling.
- **`clash_speed_test.py`** — Backward-compatible thin shim and CLI script entry point. Re-exports the package public API so old imports keep working.
- **`app.py`** — Streamlit web UI. Imports and reuses business logic and result conversion helpers from `clash_speed`. Does NOT duplicate any API/testing logic.
- **`requirements.txt`** — Dependencies: requests, rich, streamlit.

## Key Design Decisions

- **Proxy port vs API port**: The REST API port (default 9097) is NOT the HTTP proxy port. `get_proxy_port()` auto-detects the `mixed-port` from `GET /configs`, probes fallback ports, then falls back to the API port as last resort.
- **GLOBAL group excluded**: The `GLOBAL` meta-group contains all proxies but does not support `PUT /proxies/{group}` switching. `list_proxy_names()` filters it out, keeping only real Selector-type subscription groups.
- **Speed test serialization per group**: `select_proxy()` mutates group-level state, so speed tests within the same group must run sequentially. Different groups can run concurrently.
- **Latency tests are concurrent**: Uses `ThreadPoolExecutor` since the Clash `/proxies/{name}/delay` endpoint is independent per node.
- **Windows GBK encoding**: `sys.stdout.reconfigure(errors="replace")` handles flag emoji (U+1Fxxx) in proxy names on Chinese Windows consoles.
- **Fallback speed URLs**: Primary URL tries first, then FALLBACK_SPEED_URLS on failure. Some URLs return small responses (not real files) or get blocked by proxies.

## Clash Verge API Reference

- `GET /proxies` — List all proxy groups and members
- `GET /proxies/{name}/delay?timeout=5000&url=...` — Test latency for a proxy
- `PUT /proxies/{group}` with `{"name": "proxy_name"}` — Switch active proxy in a group
- `GET /configs` — Get config including `mixed-port` (HTTP proxy port)
- Auth header: `Authorization: Bearer {secret}`
- Proxy names may contain Unicode emoji — always use `requests.utils.quote(name, safe="")` for URL encoding
