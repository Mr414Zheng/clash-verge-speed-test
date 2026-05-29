"""Pure result sorting and conversion helpers."""

import csv
import io

from .models import NodeResult


def sort_results(results: list[NodeResult], sort_key: str) -> list[NodeResult]:
    """Return a sorted copy of the current result rows."""
    sorted_results = list(results)
    if sort_key == "speed":
        sorted_results.sort(key=lambda r: (r.speed_mbps is None, -(r.speed_mbps or 0)))
    else:
        sorted_results.sort(key=lambda r: (r.latency_ms is None, r.latency_ms or 999_999))
    return sorted_results


def results_to_csv(results: list[NodeResult]) -> str:
    """Convert NodeResult list to a CSV string."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["序号", "节点名称", "代理组", "延迟 (ms)", "速度 (Mbps)", "错误信息"])
    for idx, r in enumerate(results, 1):
        writer.writerow([
            idx,
            r.name,
            r.group,
            r.latency_ms if r.latency_ms is not None else "",
            f"{r.speed_mbps:.2f}" if r.speed_mbps is not None else "",
            r.error or "",
        ])
    return buf.getvalue()


def build_display_data(results: list[NodeResult]) -> list[dict]:
    """Build dataframe rows from NodeResult objects."""
    display_data = []
    for idx, r in enumerate(results, 1):
        display_data.append({
            "序号": idx,
            "节点名称": r.name,
            "代理组": r.group,
            "延迟 (ms)": r.latency_ms if r.latency_ms is not None else None,
            "速度 (Mbps)": r.speed_mbps if r.speed_mbps is not None else None,
            "错误信息": r.error or "",
        })
    return display_data
