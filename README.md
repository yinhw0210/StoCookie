# StoCookie

STO 内部系统 Cookie 自动采集工具。通过钉钉 SSO 登录后，定时采集各业务系统 Cookie 并上报到 Normandy 后台，同时心跳保活维持 Session 有效。

## 工作原理

1. **登录**：打开 SSO 页面 → 钉钉 iframe 内点击头像授权 → 桌面自动化点击钉钉客户端确认弹窗
2. **采集**：每 1 分钟访问各业务页面，提取指定 Cookie
3. **上报**：将 Cookie 按规则格式化后 POST 到 Normandy API
4. **保活**：每 3 分钟访问业务页面维持 Session，过期自动重新登录

## 平台支持

| 平台 | 登录 | 桌面自动化 |
|------|------|-----------|
| macOS | Playwright + AppleScript | System Events → AXPress |
| Windows | Playwright + pywinauto | UIA → Button click |

> **Windows 注意**：钉钉确认弹窗的 UI 结构可能与 macOS 不同，需要在 Windows 上用 Inspect.exe 或 Accessibility Insights 工具实际抓取弹窗元素结构后调整 `desktop_automation.py` 中的选择器。

## 前置条件

### macOS
1. 钉钉桌面客户端已登录
2. 系统设置 → 隐私与安全性 → 辅助功能 → 允许 Terminal / Python
3. 建议 `caffeinate -d` 防止休眠

### Windows
1. 钉钉桌面客户端已登录
2. 电源设置：从不休眠
3. 需要用 Inspect.exe 确认钉钉弹窗的实际 UI 元素结构
4. 可能需要管理员权限运行

## 安装

需要 **Python 3.9–3.13**（Playwright 依赖的 greenlet 暂不支持 3.14）。

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## 运行

```bash
python main.py
```

## 配置

编辑 `config.py`：

- `SSO_URL`：SSO 登录地址
- `HEARTBEAT_URLS`：心跳保活的业务页面列表
- `COOKIE_RULES`：Cookie 采集规则（域名、Cookie 名、格式化函数）
- `COMBO_RULES`：组合 Cookie 规则
- `REPORT_URLS`：Cookie 上报接口地址
- `COLLECT_INTERVAL_MINUTES`：采集间隔（默认 1 分钟）
- `HEARTBEAT_INTERVAL_MINUTES`：心跳间隔（默认 3 分钟）

## 项目结构

```
├── main.py                  # 入口 + 调度器
├── config.py                # 配置
├── login.py                 # SSO 登录流程
├── desktop_automation.py    # 跨平台桌面自动化（点击钉钉确认弹窗）
├── cookie_collector.py      # Cookie 采集
├── cookie_reporter.py       # Cookie 上报
├── heartbeat.py             # 心跳保活
└── requirements.txt         # 依赖
```
