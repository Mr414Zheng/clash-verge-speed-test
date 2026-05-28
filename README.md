# Clash Verge Speed Tester

Clash Verge Speed Tester 用于连接本机 Clash Verge REST API，读取可切换的代理节点，并测试节点延迟与下载速度。项目提供两种入口：

- Streamlit Web UI：适合日常可视化测试和导出结果。
- CLI 脚本：适合快速命令行测试、排序和跳过测速。

## 环境要求

- Windows 用户推荐直接使用 `run_app.bat`。
- Python 3.10 或更高版本。
- 已启动 Clash Verge，并开启外部控制 / REST API。

## Windows 一键启动

双击 `run_app.bat`，脚本会自动完成以下步骤：

1. 查找可用 Python。
2. 如果 `.venv` 不存在，则创建项目虚拟环境。
3. 安装 `requirements.txt` 中的依赖。
4. 启动 Streamlit：

```bat
python -m streamlit run app.py --server.headless=false --browser.gatherUsageStats=false
```

启动后浏览器会打开 Web UI。若安装依赖或启动失败，窗口会显示错误信息并暂停，方便查看原因。

## 手动安装与启动

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.headless=false --browser.gatherUsageStats=false
```

如果系统中安装了 Python Launcher，也可以使用：

```powershell
py -3.10 -m venv .venv
```

## CLI 示例

```powershell
.\.venv\Scripts\python.exe clash_speed_test.py --secret YOUR_SECRET
.\.venv\Scripts\python.exe clash_speed_test.py --secret YOUR_SECRET --skip-speed
.\.venv\Scripts\python.exe clash_speed_test.py --secret YOUR_SECRET --sort speed --workers 3
.\.venv\Scripts\python.exe clash_speed_test.py --api-url http://127.0.0.1:9097 --secret YOUR_SECRET --proxy-port 7890
```

常用参数：

- `--api-url`：Clash Verge REST API 地址，默认 `http://127.0.0.1:9097`。
- `--secret`：Clash Verge API Secret，对应 Bearer token。
- `--proxy-port`：HTTP 代理端口，用于下载测速；不填时会自动读取 `mixed-port`，再尝试 `7890` / `7891` / `9090`。
- `--skip-speed`：只测延迟，跳过下载测速。
- `--sort latency|speed`：按延迟或速度排序。
- `--workers`：测速并发数。速度测试会按代理组串行切换节点，不同组可并发。

## Clash Verge 配置提示

### API 地址

默认 API 地址是 `http://127.0.0.1:9097`。如果 Clash Verge 中的外部控制端口不同，请在 Web UI 的“Clash API 地址”或 CLI 的 `--api-url` 中填写实际地址。

### Secret

如果 Clash Verge 配置了 Secret，必须在 Web UI 输入 API 密钥，或在 CLI 使用 `--secret YOUR_SECRET`。本项目不会保存 Secret，也不会写入 `.env` 文件。

### 代理端口

REST API 端口不一定是 HTTP 代理端口。下载测速需要通过 HTTP 代理端口访问测速 URL。程序会优先从 `GET /configs` 读取 `mixed-port`，失败时探测常见端口，最后才回退到 API 端口。

如果自动检测不准，请在 Web UI 填写“代理端口”，或 CLI 使用：

```powershell
.\.venv\Scripts\python.exe clash_speed_test.py --secret YOUR_SECRET --proxy-port 7890
```

## 故障排查

### 401 Unauthorized

- 检查 Clash Verge 是否启用了 Secret。
- 确认 Web UI 或 `--secret` 中填写的是完整 Secret，不要包含多余空格。
- 如果刚修改 Clash Verge 配置，请重启 Clash Verge 或确认配置已重新加载。

### 连接失败

- 确认 Clash Verge 正在运行。
- 确认 REST API 地址和端口正确，例如 `http://127.0.0.1:9097`。
- 检查系统防火墙或安全软件是否阻止本机访问。

### 代理端口错误

- API 端口和代理端口是两个概念。API 端口负责 `/proxies`、`/configs` 等接口；代理端口负责 HTTP 流量转发。
- 在 Clash Verge 设置中查看 `mixed-port` 或 HTTP 代理端口。
- 手动填写 `--proxy-port` 或 Web UI 的“代理端口”后重试。

### 测速 URL 超时或首字节很慢

- 某些测速 URL 可能被节点屏蔽、返回小文件，或首字节等待时间较长。
- 可以先使用 `--skip-speed` 只测延迟，确认 API 与节点列表正常。
- 可以通过 `--speed-url` 指定更适合当前网络的测试文件。
- 降低 `--workers` 可减少并发切换节点带来的不稳定。

## 开发检查

```powershell
.\.venv\Scripts\python.exe -c "import py_compile; py_compile.compile('clash_speed_test.py', doraise=True)"
.\.venv\Scripts\python.exe -c "import py_compile; py_compile.compile('app.py', doraise=True)"
```
