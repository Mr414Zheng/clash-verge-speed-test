"""
Clash Verge Proxy Speed Tester - Streamlit Web UI

Provides an interactive web interface for testing latency and download speed
of Clash Verge proxy nodes, with sortable tables, charts, and CSV export.
"""

import os
import time
import sys

import streamlit as st

# Ensure the project directory is on the import path so the local package can
# be imported regardless of how streamlit is launched.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clash_speed import (
    ClashClient,
    DEFAULT_API_URL,
    DEFAULT_LATENCY_URL,
    DEFAULT_SPEED_URL,
    DEFAULT_TIMEOUT,
    DEFAULT_WORKERS,
    NodeResult,
    iter_latency_tests,
    iter_speed_tests,
)
from clash_speed.results import build_display_data, results_to_csv, sort_results

import requests

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Clash Verge Speed Tester",
    page_icon="⚡",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar - Configuration
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ 测试配置")

api_url = st.sidebar.text_input(
    "Clash API 地址",
    value=DEFAULT_API_URL,
    help="Clash Verge REST API 的基础 URL，例如 http://127.0.0.1:9097",
)

secret = st.sidebar.text_input(
    "API 密钥 (Secret)",
    type="password",
    help="Clash Verge REST API 的 Secret，即 Bearer token。",
)

proxy_port_override = st.sidebar.text_input(
    "代理端口",
    value="",
    help="HTTP 代理端口，用于网速测试，例如 7890。",
)

st.sidebar.markdown("---")
st.sidebar.subheader("测试选项")

sort_by = st.sidebar.selectbox(
    "默认排序",
    options=["latency", "speed"],
    format_func=lambda x: "按延迟排序" if x == "latency" else "按速度排序",
    index=0,
)

workers = st.sidebar.slider(
    "并发线程数",
    min_value=1,
    max_value=10,
    value=DEFAULT_WORKERS,
    help="延迟测试和网速测试使用的并发线程数",
)

st.sidebar.markdown("---")
st.sidebar.subheader("高级选项")

speed_url = st.sidebar.text_input(
    "测速文件 URL (可选)",
    value="",
    help="自定义下载测速的文件 URL。留空使用默认值。",
)

latency_url = st.sidebar.text_input(
    "延迟测试 URL (可选)",
    value="",
    help="自定义延迟测试的目标 URL。留空使用默认值。",
)

timeout = st.sidebar.number_input(
    "请求超时 (秒)",
    min_value=3,
    max_value=60,
    value=DEFAULT_TIMEOUT,
    step=1,
)


def show_results_dataframe(results: list[NodeResult]) -> None:
    """Render the shared result table."""
    st.dataframe(
        build_display_data(results),
        use_container_width=True,
        hide_index=True,
        column_config={
            "序号": st.column_config.NumberColumn("序号", width="small"),
            "节点名称": st.column_config.TextColumn("节点名称", width="medium"),
            "代理组": st.column_config.TextColumn("代理组", width="medium"),
            "延迟 (ms)": st.column_config.NumberColumn(
                "延迟 (ms)", format="%d", width="small"
            ),
            "速度 (Mbps)": st.column_config.NumberColumn(
                "速度 (Mbps)", format="%.2f", width="small"
            ),
            "错误信息": st.column_config.TextColumn("错误信息", width="large"),
        },
    )


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------
st.title("⚡ Clash Verge 代理测速工具")
st.markdown("测试 Clash Verge 代理节点的延迟和下载速度，支持排序、图表和 CSV 导出。")

# Session state for results
if "results" not in st.session_state:
    st.session_state["results"] = None
if "test_running" not in st.session_state:
    st.session_state["test_running"] = False
if "test_mode" not in st.session_state:
    st.session_state["test_mode"] = None
if "stop_requested" not in st.session_state:
    st.session_state["stop_requested"] = False

# ---------------------------------------------------------------------------
# Start Test button
# ---------------------------------------------------------------------------
latency_col, speed_col, stop_col, status_col = st.columns([1, 1, 1, 2])

with latency_col:
    latency_clicked = st.button(
        "延迟测试",
        disabled=st.session_state["test_running"],
        use_container_width=True,
    )

with speed_col:
    speed_clicked = st.button(
        "网速测试",
        disabled=st.session_state["test_running"],
        use_container_width=True,
    )

with stop_col:
    stop_clicked = st.button(
        "停止测试",
        disabled=not st.session_state["test_running"],
        use_container_width=True,
    )


if stop_clicked:
    st.session_state["stop_requested"] = True
    st.session_state["test_running"] = False
    st.session_state["test_mode"] = None
    st.warning("已请求停止测试，已完成的节点结果会保留。")

if latency_clicked or speed_clicked:
    # --- Validation ---
    if not api_url.strip():
        st.error("请输入 Clash API 地址。")
        st.stop()
    if not secret.strip():
        st.error("请输入 API 密钥 (Secret)。")
        st.stop()
    if not proxy_port_override.strip():
        st.error("请输入代理端口。")
        st.stop()
    try:
        proxy_port = int(proxy_port_override.strip())
        if proxy_port <= 0 or proxy_port > 65535:
            raise ValueError
    except ValueError:
        st.error("代理端口必须是 1 到 65535 之间的整数。")
        st.stop()

    st.session_state["test_running"] = True
    st.session_state["test_mode"] = "latency" if latency_clicked else "speed"
    st.session_state["stop_requested"] = False
    st.session_state["results"] = []
    st.rerun()

# ---------------------------------------------------------------------------
# Run the test (after rerun, test_running == True)
# ---------------------------------------------------------------------------
if st.session_state["test_running"]:
    test_mode = st.session_state.get("test_mode") or "latency"
    try:
        # Build client
        client = ClashClient(
            api_url=api_url,
            secret=secret.strip(),
            timeout=timeout,
        )

        try:
            proxy_port = int(proxy_port_override.strip())
            if proxy_port <= 0 or proxy_port > 65535:
                raise ValueError
            client._proxy_port = proxy_port
        except ValueError:
            st.error("代理端口必须是 1 到 65535 之间的整数。")
            st.stop()

        effective_latency_url = latency_url.strip() or DEFAULT_LATENCY_URL
        effective_speed_url = speed_url.strip() or DEFAULT_SPEED_URL

        # Progress tracking
        progress_bar = st.progress(0, text="正在获取代理列表...")

        # Step 1: Fetch proxies
        try:
            proxies = client.list_proxy_names()
        except requests.ConnectionError:
            st.error(
                f"无法连接到 Clash Verge ({api_url})。\n"
                "请确认 Clash Verge 正在运行，且 API 地址正确。"
            )
            st.stop()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 401:
                st.error("认证失败 (401)：Clash API 需要密钥，或填写的 API 密钥不正确。")
            else:
                st.error(f"API 请求失败：{exc}")
            st.stop()
        except Exception as exc:
            st.error(f"获取代理列表时出错：{exc}")
            st.stop()

        if not proxies:
            st.warning("未找到任何代理节点。请检查订阅或 API 地址。")
            st.stop()

        total_nodes = len(proxies)
        result_by_name: dict[str, NodeResult] = {}
        group_by_name = {name: group for group, name in proxies}
        completed = 0
        live_results = st.empty()

        def _publish_result(name: str, result, mode: str) -> None:
            node = result_by_name.get(name) or NodeResult(
                name=name,
                group=group_by_name.get(name, ""),
            )
            value, error = result
            if mode == "latency":
                node.latency_ms = value
                if error:
                    node.error = error
            else:
                node.speed_mbps = value
                if error:
                    node.error = error
            result_by_name[name] = node

            current_results = sort_results(list(result_by_name.values()), sort_by)
            if mode == "speed":
                current_results = sort_results(current_results, "speed")
            st.session_state["results"] = current_results
            live_results.dataframe(
                build_display_data(current_results),
                use_container_width=True,
                hide_index=True,
            )

        if test_mode == "latency":
            progress_bar.progress(5, text=f"找到 {total_nodes} 个代理节点，开始延迟测试...")
            for name, result in iter_latency_tests(
                client,
                proxies,
                effective_latency_url,
                workers,
                stop_requested=lambda: st.session_state.get("stop_requested", False),
            ):
                completed += 1
                _publish_result(name, result, "latency")
                pct = 5 + int((completed / total_nodes) * 90)
                progress_bar.progress(pct, text=f"延迟测试中 ({completed}/{total_nodes}): {name}")
        else:
            progress_bar.progress(
                5,
                text=(
                    f"找到 {total_nodes} 个代理节点，开始网速测试 "
                    f"(代理端口 {proxy_port})..."
                ),
            )
            for name, result in iter_speed_tests(
                client,
                proxies,
                effective_speed_url,
                workers,
                stop_requested=lambda: st.session_state.get("stop_requested", False),
            ):
                completed += 1
                _publish_result(name, result, "speed")
                pct = 5 + int((completed / total_nodes) * 90)
                progress_bar.progress(pct, text=f"已完成网速测试 ({completed}/{total_nodes}): {name}")

        results = st.session_state["results"] or []
        progress_bar.progress(
            100,
            text=(
                "测试已停止，已保留部分结果。"
                if st.session_state.get("stop_requested")
                else ("延迟测试完成！" if test_mode == "latency" else "网速测试完成！")
            ),
        )
        time.sleep(0.5)
        progress_bar.empty()
        st.session_state["test_running"] = False
        st.session_state["test_mode"] = None
        st.rerun()
    finally:
        st.session_state["test_running"] = False

# ---------------------------------------------------------------------------
# Display results
# ---------------------------------------------------------------------------
results: list[NodeResult] | None = st.session_state.get("results")

if results is not None and len(results) > 0:
    st.markdown("---")
    st.subheader(f"\U0001f4ca 测试结果 ({len(results)} 个节点)")

    # --- Summary statistics ---
    valid_latencies = [r.latency_ms for r in results if r.latency_ms is not None]
    valid_speeds = [r.speed_mbps for r in results if r.speed_mbps is not None]
    error_count = sum(1 for r in results if r.error)

    metric_cols = st.columns(4)
    with metric_cols[0]:
        if valid_latencies:
            best_lat = min(valid_latencies)
            st.metric("最佳延迟", f"{best_lat} ms")
        else:
            st.metric("最佳延迟", "-")
    with metric_cols[1]:
        if valid_latencies:
            avg_lat = int(sum(valid_latencies) / len(valid_latencies))
            st.metric("平均延迟", f"{avg_lat} ms")
        else:
            st.metric("平均延迟", "-")
    with metric_cols[2]:
        if valid_speeds:
            best_speed = max(valid_speeds)
            st.metric("最佳速度", f"{best_speed:.2f} Mbps")
        else:
            st.metric("最佳速度", "-")
    with metric_cols[3]:
        st.metric("错误节点数", f"{error_count}/{len(results)}")

    # --- Tabs for table / charts ---
    tab_table, tab_latency_chart, tab_speed_chart = st.tabs(
        ["\U0001f4cb 数据表格", "\U0001f4c8 延迟图表", "\U0001f4c8 速度图表"]
    )

    with tab_table:
        show_results_dataframe(results)

    with tab_latency_chart:
        lat_chart_data = {
            r.name: r.latency_ms for r in results if r.latency_ms is not None
        }
        if lat_chart_data:
            st.bar_chart(
                lat_chart_data,
                use_container_width=True,
                height=400,
                color="#ff6b6b",
            )
        else:
            st.info("没有可用的延迟数据。")

    with tab_speed_chart:
        spd_chart_data = {
            r.name: r.speed_mbps for r in results if r.speed_mbps is not None
        }
        if spd_chart_data:
            st.bar_chart(
                spd_chart_data,
                use_container_width=True,
                height=400,
                color="#4ecdc4",
            )
        else:
            st.info("没有可用的速度数据（可能已跳过测速）。")

    # --- CSV download ---
    st.markdown("---")
    csv_data = results_to_csv(results)
    st.download_button(
        label="\U0001f4e5 下载结果 (CSV)",
        data=csv_data,
        file_name="clash_speed_results.csv",
        mime="text/csv",
        use_container_width=False,
    )

elif results is not None and len(results) == 0:
    st.warning("测试完成但未获取到任何结果。")

else:
    # Initial state - no test has been run yet
    st.info("\U0001f448 请填写左侧 Clash API 地址、API 密钥和代理端口，然后选择 **延迟测试** 或 **网速测试**。")
