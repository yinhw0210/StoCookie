# 网点管家会话就绪门闩与登录稳态加固

**日期：** 2026-08-25  
**状态：** 已批准并实现（2026-08-25）  
**范围：** 方案 A（探测门闩 + 登录稳态 + 独立 SSO 调用修复 + 浏览器最大化）

## 背景

2026-08-25 运行日志显示：

1. `front.sto.cn` 独立 SSO 过期被误判为全局会话过期，触发 `clear_cookies` + 关闭全部常驻页，最终卡在 `safety-tsportal` 无法登录。
2. 启动时即便网点管家登录未成功，`spf_sid` / `engineSid` 探测协程仍立即跑搜索，超时刷屏并反向触发重登。
3. 登录成功判定过弱（只看 URL），慢网或「登录后又跳回登录页」时易误判成功。
4. Chromium 默认小视口，窗口未最大化，内容易被裁切。
5. `f3ed892` 中 `_is_independent_session_page` 被误写成实例方法调用，独立 SSO 就地重登路径会 `AttributeError`。

## 目标

- 未确认网点管家首页可用前，探测协程不搜索、不触发重登。
- 登录成功以「URL 正确 + 搜索框可见」为准；跳回认证页则允许再登一次。
- 独立 SSO 页过期只就地重登，不拖垮主会话。
- 浏览器启动即最大化，viewport 跟随窗口。

## 非目标

- 不改钉钉桌面自动化点击策略。
- 不重做 GUI。
- 不改 Cookie 上报协议。
- 不处理 PDD 独立站点逻辑（保持现状）。

## 设计

### 1. 会话就绪门闩 `_session_ready`

**位置：** `worker.py` → `BackgroundWorker`

| 动作 | `_session_ready` |
|------|------------------|
| `__init__` / 启动 | `False` |
| 登录稳态确认成功 | `True` |
| `_do_login_locked` 开始（即将 `clear_cookies`） | `False` |
| 登录失败 / 三连失败进冷却 | `False` |
| 权威判定主会话过期并进入全局重登 | `False` |

**探测协程（`_probe_spf_sid_loop` / `_probe_engine_sid_loop`）每轮开头：**

```
if not self._session_ready:
    log「等待网点管家登录就绪」
    sleep(5)
    continue
```

仍检查 `_paused` / `_maintaining`。协程在启动时即可 `create_task`（避免手动登录成功后协程起不来），但业务动作被门闩挡住。

**启动路径：** `_ensure_logged_in` 失败时跳过常驻页与首次上报（已有）；探测协程照常创建但空转等待。手动登录成功并稳态确认后，门闩打开，探测自然开始工作。

### 2. 登录稳态确认 `_confirm_wangdian_ready`

**位置：** `worker.py`（可复用已有 `_is_wangdian_search_ready` / `_get_wangdian_search_input`）

在 `_do_login_locked` 中，`login_via_dingtalk` 返回成功后调用：

1. 若当前不在已登录 URL：短暂等待或 `goto(WANGDIAN_INDEX_URL)`（超时放宽到约 30s）。
2. 等待搜索框可见（超时 **25s**，兼容慢网）。
3. 若期间 URL 变为认证页 / 虎盾：
   - 允许 **再执行 1 次** `login_via_dingtalk`（二次登录），然后再做一次搜索框确认。
4. 确认失败 → 抛错 / 返回失败，`_session_ready` 保持 `False`，计入登录重试。

虎盾页：沿用现有 `click_safety_quick_login_if_present`；`_get_dingtalk_frame` 已有约 12s 重试，本轮不改桌面自动化，但稳态层负责「进首页后必须看到搜索框」。

### 3. 独立 SSO 调用修复

**位置：** `worker.py` `_reload_persistent_pages`

```python
# 错误
self._is_independent_session_page(...)
# 正确
_is_independent_session_page(...)
```

行为保持 `f3ed892` 设计：`front` / `finance-mng` / `finance-fundmanage` / `market-cod` 过期 → 就地 `_do_sso_login_on_page`，不置 `session_expired`、不 `clear_cookies`。

### 4. 浏览器最大化

**位置：** `worker.py` `_async_main`

```python
browser = await p.chromium.launch(
    headless=False,
    args=['--start-maximized'],
)
context = await browser.new_context(no_viewport=True)
```

- Windows：`--start-maximized` 有效。
- macOS：尽量占满；`no_viewport=True` 避免默认 1280×720 裁切（比假全屏更关键）。

### 5. 冷却断路器

保留 `f3ed892` 的 `_login_cooldown_*` 与 `bypass_cooldown`；门闩与冷却互补：冷却防反复清 cookie，门闩防未登录探测。

## 成功标准

1. 启动登录失败时：日志可见「等待网点管家登录就绪」，无「搜索框 Timeout」刷屏，无探测触发的全局重登。
2. 登录成功且搜索框可见后：探测开始正常工作。
3. `front.sto.cn` 过期：出现「独立 session 页面需要重新登录」，同轮无「Session 过期，开始重新登录」。
4. 浏览器启动后窗口接近最大化，页面内容不被默认小视口裁切。
5. `py_compile` 通过；可选 offscreen 冒烟检查门闩与函数调用存在。

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 搜索框选择器变更导致永远不就绪 | 沿用现有 primary + fallback；超时失败明确日志 |
| 二次登录仍卡在虎盾无 iframe | 冷却断路器避免死亡循环；用户可手动登录（`bypass_cooldown`） |
| macOS 最大化不完全 | `no_viewport=True` 保证不裁切；最大化为尽力而为 |

## 实现触及文件

- `worker.py`（主改动）
- `login.py`（仅当稳态确认需要抽出小工具时；优先放 worker）
- `docs/superpowers/specs/2026-08-25-session-ready-gate-design.md`（本文）
