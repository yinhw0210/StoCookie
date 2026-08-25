# Session Ready Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate probes until wangdian homepage is confirmed ready; harden login with search-box confirmation + one re-login; fix independent SSO call; maximize browser window.

**Architecture:** Add `_session_ready` flag on `BackgroundWorker`. Login path clears it before `clear_cookies`, sets it only after `_confirm_wangdian_ready`. Probe loops idle while false. Fix module-level `_is_independent_session_page` call. Launch Chromium maximized with `no_viewport=True`.

**Tech Stack:** Python 3, Playwright async API, existing StoCookie worker/login.

## Global Constraints

- Only touch `worker.py` (and plan/spec docs); avoid login.py unless necessary.
- Keep existing cooldown / `bypass_cooldown` / force-login semantics.
- Do not change DingTalk desktop automation or GUI.
- No commit unless user asks.

---

### Task 1: Fix independent SSO call + browser maximize

**Files:**
- Modify: `worker.py` (`_async_main` launch; `_reload_persistent_pages` independent check)

- [ ] **Step 1:** Change launch to maximized + no_viewport

```python
browser = await p.chromium.launch(
    headless=False,
    args=['--start-maximized'],
)
context = await browser.new_context(no_viewport=True)
```

- [ ] **Step 2:** Replace `self._is_independent_session_page(...)` with `_is_independent_session_page(...)`

- [ ] **Step 3:** `python3 -m py_compile worker.py`

---

### Task 2: Session ready gate

**Files:**
- Modify: `worker.py` `__init__`, `_do_login_locked`, probe loops, `_ensure_logged_in` success path

- [ ] **Step 1:** Add `self._session_ready = False` in `__init__`

- [ ] **Step 2:** Helpers:

```python
def _set_session_ready(self, ready: bool, reason: str = ''):
    self._session_ready = ready
    if reason:
        self._emit_log(
            f'会话就绪={"是" if ready else "否"} ({reason})',
            'login',
        )
```

- [ ] **Step 3:** At start of `_do_login_locked` (before clear_cookies): `_set_session_ready(False, '开始全局重登')`

- [ ] **Step 4:** On login success after confirm: `_set_session_ready(True, '登录稳态确认通过')`

- [ ] **Step 5:** On login fail-out: ensure `_session_ready` stays False

- [ ] **Step 6:** In `_probe_spf_sid_loop` and `_probe_engine_sid_loop`, after pause/maintaining checks:

```python
if not self._session_ready:
    self._emit_log('[spf_sid探测] 等待网点管家登录就绪', 'report')  # or engineSid
    await asyncio.sleep(5)
    continue
```

- [ ] **Step 7:** If `_ensure_logged_in` finds session already valid at startup, still run `_confirm_wangdian_ready` on a temp page (or existing check) before `_set_session_ready(True)` — if only cookie check, open index briefly to confirm search box.

---

### Task 3: Login steady-state confirmation

**Files:**
- Modify: `worker.py` — add `_confirm_wangdian_ready`, call from `_do_login_locked`

- [ ] **Step 1:** Implement:

```python
async def _confirm_wangdian_ready(self, page, *, allow_relogin: bool = True) -> None:
    """Raise if wangdian index search box not ready. Optionally one re-login."""
    from config import is_auth_url, is_logged_in_url

    async def _ensure_index_and_search():
        if not is_logged_in_url(page.url) or is_auth_url(page.url):
            await page.goto(WANGDIAN_INDEX_URL, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(2000)
        if is_auth_url(page.url):
            raise RuntimeError(f'确认就绪时仍在认证页: {page.url}')
        await self._dismiss_announcement(page, 'login')
        # wait up to 25s for search box
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if await self._is_wangdian_search_ready(page):
                return
            if is_auth_url(page.url):
                raise RuntimeError(f'确认就绪时跳回认证页: {page.url}')
            await page.wait_for_timeout(1000)
        raise RuntimeError('网点管家搜索框未在时限内就绪')

    try:
        await _ensure_index_and_search()
    except Exception as first_err:
        if not allow_relogin:
            raise
        self._emit_log(f'登录稳态确认失败，尝试二次登录: {first_err}', 'login')
        await login_via_dingtalk(page)
        await _ensure_index_and_search()
```

- [ ] **Step 2:** In `_do_login_locked` after `login_via_dingtalk(page)`:

```python
await self._confirm_wangdian_ready(page, allow_relogin=True)
await self._replace_login_page(page)
...
self._set_session_ready(True, '登录稳态确认通过')
```

- [ ] **Step 3:** Startup path when session already valid: confirm ready before opening probes gate.

---

### Task 4: Verify

- [ ] **Step 1:** `python3 -m py_compile worker.py`
- [ ] **Step 2:** Grep confirm: no `self._is_independent_session_page`; has `_session_ready`, `_confirm_wangdian_ready`, `--start-maximized`, `no_viewport=True`
- [ ] **Step 3:** Update spec status to approved/implemented note if needed

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| `_session_ready` gate | Task 2 |
| Probe wait without re-login | Task 2 |
| Steady-state + second login | Task 3 |
| Independent SSO fix | Task 1 |
| Browser maximize | Task 1 |
| Keep cooldown | unchanged |
