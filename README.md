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
| Windows | Playwright + pywinauto | UIA Invoke/click_input → 坐标兜底 |

> **Windows 注意**：钉钉确认弹窗可能是 WebView 结构。程序会在日志里输出疑似弹窗的 title、class、rect 和带名称的 UIA 控件摘要，便于继续用 Inspect.exe / Accessibility Insights 对照。

## 前置条件

### macOS
1. 钉钉桌面客户端已登录
2. 系统设置 → 隐私与安全性 → 辅助功能 → 允许 Terminal / Python
3. 建议 `caffeinate -d` 防止休眠

### Windows
1. 钉钉桌面客户端已登录
2. 电源设置：从不休眠
3. 如自动点击失败，用日志里的弹窗信息配合 Inspect.exe 确认实际 UI 元素结构
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

启动后会显示 GUI 窗口（PySide6），包含：
- 状态面板：登录状态、同步结果、心跳状态、倒计时
- 操作按钮：立即同步、重新登录
- 日志面板：实时显示运行日志
- 系统托盘：关闭窗口后最小化到托盘继续运行

## Windows 打包

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 下载 Chromium 到 browsers/ 目录
set PLAYWRIGHT_BROWSERS_PATH=.\browsers
playwright install chromium

# 3. PyInstaller 打包
pyinstaller StoCookie.spec

# 4. Inno Setup 生成安装包
iscc installer.iss
# 输出: StoCookie_Setup.exe
```

安装包功能：
- 桌面快捷方式 + 开始菜单
- 开机自启（注册表）
- 内置 Chromium 浏览器

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
├── main.py                  # 入口（启动 GUI + 后台任务）
├── config.py                # 配置（路径动态化，支持 PyInstaller frozen）
├── worker.py                # 后台工作线程（Playwright + 定时调度）
├── login.py                 # SSO 登录流程
├── desktop_automation.py    # 跨平台桌面自动化（点击钉钉确认弹窗）
├── cookie_collector.py      # Cookie 采集
├── cookie_reporter.py       # Cookie 上报
├── heartbeat.py             # 心跳保活
├── gui/
│   ├── __init__.py
│   ├── main_window.py       # 主窗口（状态面板 + 日志 + 按钮）
│   ├── tray_icon.py         # 系统托盘
│   └── resources/
│       └── icon.ico         # 应用图标
├── StoCookie.spec           # PyInstaller 打包配置
├── installer.iss            # Inno Setup 安装包脚本
└── requirements.txt         # 依赖
```
