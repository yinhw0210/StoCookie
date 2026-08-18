# StoCookie 项目理解（代码 → 业务）

## 一、业务本质

StoCookie 是**申通（STO）网点内部系统的「登录态代理」工具**：在本机用真实浏览器（Playwright 驱动 Chromium，非无头）维持各业务系统的登录会话，定时把 Cookie 按约定格式上报到 Normandy 后台（`slinghang.cn` / `lysto.com.cn` 两个端点），后端再用这些 Cookie 以网点身份调用 STO 内部接口。

演进路径：`CookieTool/`（Chrome 扩展，MV3，每分钟 chrome.cookies 轮询上报）→ 当前 Python 桌面应用（Playwright + PySide6 GUI，跨 macOS/Windows，PyInstaller + Inno Setup 分发）。CookieTool 是旧版参考实现，功能已全部迁移。

## 二、架构与模块

```
main.py                PySide6 入口 + loguru（日滚动日志，保留30天）
worker.py              核心：后台线程 + asyncio 事件循环，所有调度在此
login.py               钉钉 SSO 登录子流程（iframe 操作、虎盾、多角色）
desktop_automation.py  跨平台点击钉钉桌面客户端「登录」确认弹窗
cookie_collector.py    按 COOKIE_RULES / COMBO_RULES / KFSD 规则采集
cookie_reporter.py     httpx GET 上报，带 DNS 故障转移（trust_env=False 绕代理）
sites/pdd.py           PDD 站点驱动（独立 context，账密登录 + 反风控指纹伪装）
gui/                   main_window（状态卡/上报矩阵/日志Tab）、tray_icon、settings_dialog、styles
CookieTool/            旧版 Chrome 扩展（仅参考）
StoCookie.spec / installer.iss   PyInstaller + Inno Setup 打包
```

## 三、运行时模型（worker.py 关键）

一个后台线程跑一个 asyncio loop，内含 **1 个主循环 + 2 个独立协程 + 1 个事件监听**：

1. **主循环**（5s tick）：
   - 采集周期（默认 60min）：检查 Session → reload 常驻页 → 采集 → 上报
   - 心跳周期（默认 30min）：只 reload 常驻页保活，发现过期则重登
   - 手动事件：立即同步 / 重新登录 / 暂停
2. **spf_sid 探测协程**：独立 page，随机 30/60/180s 在 wangdian 首页搜索「订单查询」，检测 spf_sid 变化→立即全量上报；cookie 缺失→触发重登。已知值持久化到 settings.json 跨重启去重。
3. **engineSid 协程**（客户经营分析，默认 30min）：搜索「客户经营分析」（同页 iframe 打开 zc.sto.cn）→ 遍历 frames 读 sessionStorage.engineSid → 以 `enginesid=...` 上报。每次刷新值都变，不去重。
4. **mapAreaDetail 响应监听**：context.on('response')，命中 `wangdian.sto.cn/order/collectMap/query/detail/mapAreaDetail` → 5 分钟限流触发 `KFSD=wangdian全量cookie` 上报。

**并发安全**（代码里两把锁，都是踩过坑的）：
- `_wangdian_search_lock`：所有操作 wangdian 首页搜索框的路径互斥，防 Target crashed
- `_login_lock`：主循环与探测协程都可能触发重登，防并发 clear_cookies 互相破坏

**登录链路**：wangdian.sto.cn → （虎盾 safety-tsportal 快速登录）→ 钉钉 OAuth2 iframe（点头像→立即登录→授权同意）→ 桌面自动化点钉钉客户端「登录」弹窗（macOS AppleScript AXPress / Windows pywinauto UIA + 坐标兜底）→ 多角色页选第一个角色进入。market-cod.sto.cn 有独立 session，单独走 `_do_sso_login_on_page`。

**Cookie 上报清单**（9 单条 + 3 组合 + KFSD + PDD + engineSid）：SESSION(finance-mng)、cod、finance(finance-fundmanage SESSION 改名)、fin_report_session、spf_sid、stoToken、sid_cfo、WD_SESSION、TOKEN(page.sto.cn)、WD_SESSION+TSID、CFO_DOWNLOAD(sid_cfo+WD_SESSION+TSID)、WD_STO(stoToken+WD_SESSION)、KFSD(wangdian全量)、SUB_PASS_ID(PDD)、enginesid(ZC)。上报附带 `isScript=1&accountName=<localStorage originalUserData.userName>`。

## 四、配置与持久化

- `config.py`：全部常量（URL、选择器、规则、间隔），支持 PyInstaller frozen 路径
- `settings.json`：运行时设置（间隔、PDD 账密、zc 开关、known_spf_sid_values）
- 日志：`logs/stocookie-YYYY-MM-DD.log`，DEBUG 级，日滚动保留 30 天

## 五、已发现的问题/坏味道（待任务时参考）

1. **Bug**：`gui/main_window.py:179` 用 `self._worker.is_paused`，但 `worker.py` 只有 `_paused` 字段、无 `is_paused` 属性 → 点主窗口「暂停」按钮会 AttributeError（托盘菜单不受影响，它用自己的文本判断）。
2. **文档过时**：README 说采集间隔默认 1 分钟（实际 config 60 分钟）；README 列了 `heartbeat.py`（不存在，已并入 worker.py）；README 说 slinghang 上报关闭（config 里两个 URL 都启用，仅注释说关闭）。
3. **死代码**：`requirements.txt` 的 apscheduler 未被使用（spec hiddenimports 还引用着）；`_check_proactive_refresh_due` 被 `return False` 禁用（预判刷新已被 spf_sid 探测协程替代）；实操中心/TOKEN 相关分支大段注释保留。
4. **敏感信息明文**：`settings.json` 明文 PDD 密码；`test.py` 硬编码另一组账号密码。
5. **杂物**：`logs/` 下有一个以 HTML 片段命名的 `.xml` 文件；`CookieTool/popup.js:214` 有游离数字 `78588888`。
6. **小不一致**：`_resolve_cookie_label` 对 `WD_SESSION+TSID` 组合返回的标签与 `COOKIE_REPORT_LABELS` 的 key 体系靠运行时兜底匹配，逻辑正确但脆弱。
