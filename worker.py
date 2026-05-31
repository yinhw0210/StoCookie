import asyncio
import json
import os
import threading
import time
from datetime import datetime

from loguru import logger
from PySide6.QtCore import QObject, Signal

from config import (
    BROWSERS_DIR,
    COLLECT_INTERVAL_MINUTES,
    FINANCE_FUNDMANAGE_URL,
    HEARTBEAT_INTERVAL_MINUTES,
    LOG_DIR,
    PERSISTENT_PAGES,
    SETTINGS_PATH,
    SSO_URL,
    STORAGE_DIR,
    STORAGE_STATE_PATH,
    WANGDIAN_ANNOUNCEMENT_CLOSE_SELECTOR,
    WANGDIAN_INDEX_URL,
    WANGDIAN_MAP_AREA_DETAIL_URL_MARKER,
    WANGDIAN_NAV_SELECTOR,
    WANGDIAN_SEARCH_FIRST_RESULT_SELECTOR,
    WANGDIAN_SEARCH_INPUT_SELECTOR,
    WANGDIAN_SEARCH_KEYWORDS,
    WANGDIAN_TRIGGER_INTERVAL_SECONDS,
    is_auth_url,
    is_logged_in_url,
)
from cookie_collector import build_wangdian_kfsd_payload, collect_cookies, EXPECTED_REPORT_ITEMS
from cookie_reporter import report_cookies
from login import login_via_dingtalk, wait_for_wangdian_entry_or_role

COOKIE_REPORT_LABELS = {
    'SESSION=': 'SESSION (finance-mng)',
    'cod=': 'cod (market-cod)',
    'finance=': 'finance (finance-fundmanage)',
    'spf_sid=': 'spf_sid (wutonggateway)',
    'stoToken=': 'stoToken (wutonggateway)',
    'sid_cfo=': 'sid_cfo (wutonggateway)',
    'WD_SESSION=': 'WD_SESSION (wutonggateway)',
    'KFSD=': 'KFSD (wangdian全量)',
    'CFO_DOWNLOAD': 'CFO_DOWNLOAD 组合',
    'WD_STO=': 'WD_STO 组合',
}


def _load_settings() -> dict:
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


class WorkerSignals(QObject):
    log_message = Signal(str, str)  # (message, category)
    status_update = Signal(dict)


class BackgroundWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.signals = WorkerSignals()
        self._manual_sync_event = threading.Event()
        self._manual_login_event = threading.Event()
        self._stop_event = threading.Event()
        self._paused = False
        self._loop = None
        self._login_page = None
        self._last_wangdian_trigger = 0.0
        self._response_listener_registered = False
        self._persistent_pages: dict[str, object] = {}
        self._pdd = None

        settings = _load_settings()
        self._collect_interval = settings.get('collect_interval', COLLECT_INTERVAL_MINUTES)
        self._heartbeat_interval = settings.get('heartbeat_interval', HEARTBEAT_INTERVAL_MINUTES)
        self._proactive_refresh_rules = settings.get('proactive_refresh', [])
        self._cookie_obtained_at: dict[str, float] = {}

    @property
    def collect_interval(self):
        return self._collect_interval

    @property
    def heartbeat_interval(self):
        return self._heartbeat_interval

    def run(self):
        os.makedirs(STORAGE_DIR, exist_ok=True)
        os.makedirs(LOG_DIR, exist_ok=True)

        if os.path.isdir(BROWSERS_DIR):
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = BROWSERS_DIR

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as e:
            self._emit_log(f'后台线程异常退出: {e}', 'general')
        finally:
            self._loop.close()

    async def _async_main(self):
        from playwright.async_api import async_playwright

        self._emit_status({'login': '启动中...'})

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)

            if os.path.exists(STORAGE_STATE_PATH):
                self._emit_log('恢复已有 Session...', 'login')
                context = await browser.new_context(storage_state=STORAGE_STATE_PATH)
            else:
                self._emit_log('无已有 Session，创建新 context', 'login')
                context = await browser.new_context()

            self._register_wangdian_trigger(context)

            login_ok = await self._ensure_logged_in(context, 'startup')
            if login_ok:
                await self._open_persistent_pages(context)
                self._emit_status({'sync': '等待同步'})
                self._emit_log('启动 SSO 校验完成，常驻页面已打开，执行首次上报', 'report')
                await self._do_collect_and_report(context)
            else:
                self._emit_status({'sync': '等待登录'})
                self._emit_log('启动登录未完成，跳过首次 Cookie 同步', 'report')

            # PDD 站点初始化
            await self._init_pdd(browser)

            last_sync = time.time()

            while not self._stop_event.is_set():
                if self._paused:
                    self._emit_status({'paused': True})
                    await asyncio.sleep(5)
                    continue

                if self._manual_login_event.is_set():
                    self._manual_login_event.clear()
                    await self._do_login(context)
                    await self._open_persistent_pages(context)

                if self._manual_sync_event.is_set():
                    self._manual_sync_event.clear()
                    await self._do_sync_cycle(context)
                    if self._pdd:
                        await self._do_pdd_sync_cycle()
                    last_sync = time.time()

                now = time.time()
                sync_due = (now - last_sync) >= self._collect_interval * 60
                proactive_due = self._check_proactive_refresh_due(now)

                if proactive_due:
                    await self._do_proactive_refresh(context)
                    if self._pdd:
                        await self._do_pdd_sync_cycle()
                    last_sync = time.time()
                elif sync_due:
                    await self._do_sync_cycle(context)
                    if self._pdd:
                        await self._do_pdd_sync_cycle()
                    last_sync = time.time()

                next_sync = max(0, self._collect_interval * 60 - (time.time() - last_sync))
                self._emit_status({
                    'next_collect': int(next_sync),
                    'next_heartbeat': int(next_sync),
                    'paused': False,
                })

                await asyncio.sleep(5)

            await browser.close()

    async def _check_session(self, context) -> bool:
        # 优先复用已有的 wangdian 页面做 reload 检测
        wangdian_page = self._persistent_pages.get(WANGDIAN_INDEX_URL)
        if wangdian_page and not wangdian_page.is_closed():
            self._emit_log('复用已有 wangdian 页面检测 Session（reload）', 'login')
            try:
                await wangdian_page.reload(wait_until='domcontentloaded', timeout=20000)
                await wangdian_page.wait_for_timeout(3000)
                url = wangdian_page.url
                self._emit_log(f'wangdian reload 后 URL: {url}', 'login')
                if is_auth_url(url):
                    self._emit_log(f'Session 过期，页面跳转到认证页: {url}', 'login')
                    return True
                self._emit_log('Session 有效，wangdian 页面未跳转', 'login')
                return False
            except Exception as e:
                self._emit_log(f'复用 wangdian 页面检测失败: {e}，fallback 新开页面', 'login')

        # fallback: 新开页面检测（仅在没有已打开的 wangdian 页面时使用）
        page = await context.new_page()
        try:
            self._emit_log(f'新开页面访问登录入口检查 Session: {SSO_URL}', 'login')
            await page.goto(SSO_URL, wait_until='domcontentloaded', timeout=20000)
            await page.wait_for_timeout(3000)
            url = page.url
            self._emit_log(f'登录入口检查完成，当前 URL: {url}', 'login')

            if is_logged_in_url(url):
                self._emit_log(f'Session 有效，网点入口未跳转认证页: {url}', 'login')
                return False

            if is_auth_url(url):
                self._emit_log(f'Session 过期，网点入口已跳转认证页: {url}', 'login')
                return True

            # 等待看是否能进入系统
            try:
                await wait_for_wangdian_entry_or_role(page, timeout_ms=15000)
            except Exception:
                pass

            if is_logged_in_url(page.url):
                self._emit_log(f'Session 有效，已进入网点系统: {page.url}', 'login')
                return False

            self._emit_log(f'Session 状态不明，当前 URL: {page.url}', 'login')
            return True
        except Exception as e:
            self._emit_log(f'Session 检测失败: {e}', 'login')
            return True
        finally:
            await page.close()

    async def _do_login(self, context):
        self._emit_status({'login': '登录中...'})
        for attempt in range(3):
            self._emit_log(f'开始登录... (第{attempt+1}次)', 'login')
            page = await context.new_page()
            try:
                await login_via_dingtalk(page)
                await context.storage_state(path=STORAGE_STATE_PATH)
                await self._replace_login_page(page)
                now = datetime.now().strftime('%H:%M:%S')
                self._emit_status({'login': f'已登录 ({now})', 'login_time': now})
                self._emit_log('登录成功', 'login')
                return True
            except Exception as e:
                if attempt < 2:
                    self._emit_log(f'登录失败({attempt+1}/3)，30秒后重试: {e}', 'login')
                    await asyncio.sleep(30)
                else:
                    self._emit_status({'login': f'登录失败 (已重试3次)'})
                    self._emit_log(f'登录失败，已重试3次: {e}', 'login')
            finally:
                if page is not self._login_page:
                    await page.close()
        return False

    async def _replace_login_page(self, page):
        old_page = self._login_page
        self._login_page = page
        if old_page and old_page is not page:
            try:
                await old_page.close()
            except Exception:
                pass

    async def _close_login_page(self):
        if self._login_page and not self._login_page.is_closed():
            try:
                await self._login_page.close()
                self._emit_log('已关闭遗留的登录页面', 'login')
            except Exception:
                pass
            self._login_page = None

    async def _do_sso_login_on_page(self, page):
        """在已经跳转到 SSO 页面的 page 上完成钉钉登录，不导航到 wangdian"""
        from login import (
            _get_dingtalk_frame, _dismiss_cookie_dialog, _click_avatar,
            _click_confirm_login, _click_consent, click_safety_quick_login_if_present,
            _has_dingtalk_frame,
        )
        from desktop_automation import click_dingtalk_confirm

        await page.wait_for_timeout(2000)

        if await click_safety_quick_login_if_present(page):
            await page.wait_for_timeout(3000)
            if not is_auth_url(page.url):
                return  # 已离开认证页，成功
            # 仍在认证页，检查是否有钉钉 iframe
            if not await _has_dingtalk_frame(page):
                await page.wait_for_timeout(3000)
                if not is_auth_url(page.url):
                    return
                self._emit_log('虎盾快速登录后仍在认证页，尝试钉钉流程', 'login')
            # 继续执行下面的钉钉登录流程

        dd_frame = await _get_dingtalk_frame(page)
        self._emit_log(f'已定位钉钉 iframe: {dd_frame.url}', 'login')

        await _dismiss_cookie_dialog(dd_frame)

        confirm_task = asyncio.create_task(click_dingtalk_confirm(timeout=30))
        try:
            await _click_avatar(dd_frame)
            await _click_confirm_login(dd_frame)
            await _click_consent(dd_frame)
            # 等待页面离开 SSO（不要求进入 wangdian，只要不在 SSO 就行）
            for _ in range(30):
                await page.wait_for_timeout(1000)
                if not is_auth_url(page.url):
                    break
        finally:
            if not confirm_task.done():
                confirm_task.cancel()
                try:
                    await confirm_task
                except (asyncio.CancelledError, Exception):
                    pass

    def _register_wangdian_trigger(self, context):
        if self._response_listener_registered:
            return
        context.on('response', lambda response: self._schedule_wangdian_trigger(context, response))
        self._response_listener_registered = True

    def _schedule_wangdian_trigger(self, context, response):
        if WANGDIAN_MAP_AREA_DETAIL_URL_MARKER not in response.url:
            return
        if not self._loop or self._loop.is_closed():
            return
        self._loop.create_task(self._handle_wangdian_trigger(context, response.url))

    async def _handle_wangdian_trigger(self, context, url: str):
        now = time.time()
        elapsed = now - self._last_wangdian_trigger
        if elapsed < WANGDIAN_TRIGGER_INTERVAL_SECONDS:
            remain = int(WANGDIAN_TRIGGER_INTERVAL_SECONDS - elapsed)
            self._emit_log(f'mapAreaDetail 触发但仍在限流窗口，剩余{remain}秒，忽略: {url}', 'report')
            return

        self._last_wangdian_trigger = now
        try:
            self._emit_log(f'mapAreaDetail 触发 KFSD 上报: {url}', 'report')
            all_cookies = await context.cookies('https://wangdian.sto.cn')
            self._emit_log(f'mapAreaDetail 读取 wangdian Cookie 数: {len(all_cookies)}', 'report')
            payload = build_wangdian_kfsd_payload(all_cookies)
            if not payload:
                self._emit_log('mapAreaDetail 触发但未找到 wangdian Cookie', 'report')
                return

            self._emit_log(f'mapAreaDetail 生成 KFSD payload: {payload[:80]}...', 'report')
            account_name = await self._get_account_name()
            extra_params = {'isScript': '1', 'accountName': account_name}
            reports = await report_cookies([payload], emit_log=self._emit_log, extra_params=extra_params)
            total_success = sum(1 for entry in reports for r in entry['results'] if r['ok'])
            total_fail = sum(1 for entry in reports for r in entry['results'] if not r['ok'])
            for entry in reports:
                results_str = ' / '.join(
                    f'{r["url"]} ✓' if r['ok'] else f'{r["url"]} ✗({r["error"]})'
                    for r in entry['results']
                )
                self._emit_log(f'mapAreaDetail KFSD 明细: {entry["cookie"]}... → {results_str}', 'report')
            self._emit_log(
                f'mapAreaDetail 触发 KFSD 上报完成: 成功{total_success}/失败{total_fail} ({url})',
                'report',
            )
        except Exception as e:
            self._emit_log(f'mapAreaDetail 触发 KFSD 上报异常: {e}', 'report')

    async def _ensure_logged_in(self, context, reason: str) -> bool:
        self._emit_log(f'执行 SSO 前置校验: {reason}', 'login')
        need_login = await self._check_session(context)
        if not need_login:
            self._emit_status({'login': '已登录'})
            self._emit_log('Session 有效，允许继续 Cookie 流程', 'login')
            return True

        self._emit_log('Session 无效或未登录，开始单点登录流程', 'login')
        login_ok = await self._do_login(context)
        if not login_ok:
            self._emit_status({'login': '登录失败', 'sync': '等待登录'})
            self._emit_log('单点登录未完成，禁止访问业务页和上报 Cookie', 'login')
            return False
        return True

    async def _dismiss_announcement(self, page):
        try:
            close_btn = page.locator(WANGDIAN_ANNOUNCEMENT_CLOSE_SELECTOR).first
            if await close_btn.is_visible(timeout=3000):
                await close_btn.click()
                await page.wait_for_timeout(500)
                self._emit_log('公告弹窗已关闭', 'general')
        except Exception:
            pass

    async def _search_and_click(self, page, keyword: str):
        try:
            search_input = page.locator(WANGDIAN_SEARCH_INPUT_SELECTOR).first
            await search_input.click(timeout=5000)
            await search_input.fill('')
            await page.wait_for_timeout(300)
            await search_input.fill(keyword)
            self._emit_log(f'搜索框已输入「{keyword}」，等待联想框出现...', 'general')

            first_result = page.locator(WANGDIAN_SEARCH_FIRST_RESULT_SELECTOR).first
            await first_result.wait_for(state='visible', timeout=8000)
            self._emit_log(f'联想框已出现，点击第一个结果...', 'general')
            await first_result.click()
            await page.wait_for_timeout(2000)
            self._emit_log(f'搜索「{keyword}」点击完成，当前 URL: {page.url}', 'general')
            return True
        except Exception as e:
            self._emit_log(f'搜索「{keyword}」失败: {e}', 'general')
            return False

    async def _handle_wangdian_index(self, context, page):
        await self._dismiss_announcement(page)

        # 搜索「结算账户交易明细」触发 cookie 生成
        await self._search_and_click(page, WANGDIAN_SEARCH_KEYWORDS[0])

        # 新开标签页打开 finance-fundmanage
        try:
            fm_page = await context.new_page()
            await fm_page.goto(FINANCE_FUNDMANAGE_URL, wait_until='domcontentloaded', timeout=15000)
            await fm_page.wait_for_timeout(2000)
            self._persistent_pages[FINANCE_FUNDMANAGE_URL] = fm_page
            self._emit_log(f'常驻页面已打开: {FINANCE_FUNDMANAGE_URL}', 'general')
        except Exception as e:
            self._emit_log(f'finance-fundmanage 页面打开失败: {e}', 'general')

        # 回到 wangdian/index 搜索「网点账单」
        await page.goto(WANGDIAN_INDEX_URL, wait_until='domcontentloaded', timeout=15000)
        await page.wait_for_timeout(2000)
        await self._dismiss_announcement(page)
        await self._search_and_click(page, WANGDIAN_SEARCH_KEYWORDS[1])

    async def _open_persistent_pages(self, context):
        self._emit_log('开始打开常驻页面...', 'general')
        for url in PERSISTENT_PAGES:
            if url in self._persistent_pages:
                page = self._persistent_pages[url]
                if not page.is_closed():
                    self._emit_log(f'常驻页面已存在且有效，跳过: {url}', 'general')
                    continue
                else:
                    self._emit_log(f'常驻页面已关闭，重新打开: {url}', 'general')
            try:
                page = await context.new_page()
                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                await page.wait_for_timeout(2000)
                self._emit_log(f'常驻页面导航完成，当前 URL: {page.url}', 'general')

                if is_auth_url(page.url):
                    if 'page.sto.cn' in url:
                        # page.sto.cn 有独立 session，SSO 登录后会自动跳转回目标页
                        # 只需要完成钉钉登录流程，然后等待页面离开 SSO 即可
                        self._emit_log(f'page.sto.cn 需要独立登录，等待 SSO 完成...', 'login')
                        try:
                            await self._do_sso_login_on_page(page)
                            self._emit_log(f'page.sto.cn 登录完成，当前 URL: {page.url}', 'login')
                        except Exception as e:
                            self._emit_log(f'page.sto.cn 登录失败: {e}，跳过此页面', 'login')
                            await page.close()
                            continue
                    elif 'market-cod.sto.cn' in url:
                        # market-cod 有独立 session，当前页面已经在 SSO 页
                        self._emit_log(f'market-cod 需要独立登录，执行登录流程', 'login')
                        try:
                            await self._do_sso_login_on_page(page)
                            await page.wait_for_timeout(2000)
                            # 登录后跳转到 /cod/home/index，需要再次导航到目标页
                            if 'topayment/siteOrder/list' not in page.url:
                                self._emit_log(f'market-cod 登录后跳转到: {page.url}，再次导航到目标页', 'general')
                                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                                await page.wait_for_timeout(2000)
                            self._emit_log(f'market-cod 登录完成，当前 URL: {page.url}', 'login')
                        except Exception as e:
                            self._emit_log(f'market-cod 登录失败: {e}', 'login')
                            await page.close()
                            continue
                    else:
                        # 其他页面（wangdian 子页面等）共享 wangdian session，不应该出现 SSO
                        self._emit_log(f'常驻页面意外跳转到登录页: {url} → {page.url}', 'login')
                        try:
                            await self._do_sso_login_on_page(page)
                            await page.wait_for_timeout(2000)
                            if url not in page.url:
                                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                                await page.wait_for_timeout(2000)
                        except Exception as e:
                            self._emit_log(f'常驻页面登录失败: {url} -> {e}', 'login')
                            await page.close()
                            continue

                if 'wangdian.sto.cn/index' in url:
                    await self._handle_wangdian_index(context, page)
                self._persistent_pages[url] = page
                self._emit_log(f'常驻页面已打开: {url}', 'general')
            except Exception as e:
                self._emit_log(f'常驻页面打开失败: {url} -> {e}', 'general')
        # 关闭 _do_login 遗留的登录页面
        await self._close_login_page()
        await context.storage_state(path=STORAGE_STATE_PATH)
        self._emit_log(f'常驻页面打开完成，共 {len(self._persistent_pages)} 个', 'general')

    async def _reload_persistent_pages(self, context) -> bool:
        session_expired = False
        self._emit_log(f'reload 常驻页面: {len(self._persistent_pages)} 个', 'heartbeat')
        for url, page in list(self._persistent_pages.items()):
            try:
                if page.is_closed():
                    self._emit_log(f'常驻页面已关闭，重新打开: {url}', 'heartbeat')
                    page = await context.new_page()
                    await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                    self._persistent_pages[url] = page
                else:
                    self._emit_log(f'reload: {url}', 'heartbeat')
                    await page.reload(wait_until='domcontentloaded', timeout=15000)

                await page.wait_for_timeout(2000)
                self._emit_log(f'reload 后 URL: {page.url}', 'heartbeat')

                if is_auth_url(page.url):
                    # page.sto.cn 和 market-cod 有独立 session，跳转到 SSO 不代表全局过期
                    # 对这些页面单独走登录流程（当前页面已在 SSO，用 skip_navigate）
                    if 'page.sto.cn' in url or 'market-cod.sto.cn' in url:
                        self._emit_log(f'独立 session 页面需要重新登录: {url}', 'heartbeat')
                        try:
                            await self._do_sso_login_on_page(page)
                            await page.wait_for_timeout(2000)
                            if url not in page.url:
                                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                                await page.wait_for_timeout(2000)
                            if 'market-cod.sto.cn' in url and 'topayment/siteOrder/list' not in page.url:
                                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                                await page.wait_for_timeout(2000)
                            self._emit_log(f'独立 session 页面重新登录完成: {url}', 'heartbeat')
                        except Exception as e:
                            self._emit_log(f'独立 session 页面登录失败: {url} -> {e}', 'heartbeat')
                    else:
                        self._emit_log(f'常驻页面 reload 后跳转到登录页: {url} → {page.url}', 'heartbeat')
                        session_expired = True
                        break

                if 'wangdian.sto.cn/index' in url:
                    await self._dismiss_announcement(page)
            except Exception as e:
                self._emit_log(f'常驻页面 reload 失败: {url} -> {e}', 'heartbeat')
                # finance-fundmanage 需要通过 wangdian 搜索入口打开，不能直接 goto
                if FINANCE_FUNDMANAGE_URL in url:
                    self._emit_log(f'finance-fundmanage 需要通过搜索入口重新打开', 'heartbeat')
                    await self._reopen_finance_fundmanage(context)
                else:
                    try:
                        page = await context.new_page()
                        await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                        self._persistent_pages[url] = page
                        self._emit_log(f'常驻页面重新打开成功: {url}', 'heartbeat')
                    except Exception as e2:
                        self._emit_log(f'常驻页面重新打开也失败: {url} -> {e2}', 'heartbeat')

        if not session_expired:
            await context.storage_state(path=STORAGE_STATE_PATH)
        return not session_expired

    async def _reopen_finance_fundmanage(self, context):
        """通过 wangdian/index 搜索「结算账户交易明细」后打开 finance-fundmanage 页面"""
        try:
            wangdian_page = self._persistent_pages.get(WANGDIAN_INDEX_URL)
            if not wangdian_page or wangdian_page.is_closed():
                wangdian_page = await context.new_page()
                await wangdian_page.goto(WANGDIAN_INDEX_URL, wait_until='domcontentloaded', timeout=15000)
                await wangdian_page.wait_for_timeout(2000)
                self._persistent_pages[WANGDIAN_INDEX_URL] = wangdian_page

            await self._dismiss_announcement(wangdian_page)
            await self._search_and_click(wangdian_page, WANGDIAN_SEARCH_KEYWORDS[0])

            # 关闭旧的 finance-fundmanage 页面
            old_page = self._persistent_pages.get(FINANCE_FUNDMANAGE_URL)
            if old_page and not old_page.is_closed():
                await old_page.close()

            fm_page = await context.new_page()
            await fm_page.goto(FINANCE_FUNDMANAGE_URL, wait_until='domcontentloaded', timeout=15000)
            await fm_page.wait_for_timeout(2000)
            self._persistent_pages[FINANCE_FUNDMANAGE_URL] = fm_page
            self._emit_log(f'finance-fundmanage 通过搜索入口重新打开成功', 'heartbeat')
        except Exception as e:
            self._emit_log(f'finance-fundmanage 通过搜索入口重新打开失败: {e}', 'heartbeat')

    async def _get_account_name(self) -> str:
        """从 wangdian.sto.cn/index 页面的 localStorage 中获取 userName"""
        try:
            wangdian_page = self._persistent_pages.get(WANGDIAN_INDEX_URL)
            if not wangdian_page or wangdian_page.is_closed():
                self._emit_log('wangdian 页面不可用，accountName 取空', 'general')
                return ''

            user_name = await wangdian_page.evaluate('''() => {
                try {
                    const data = localStorage.getItem('originalUserData');
                    if (!data) return '';
                    const obj = JSON.parse(data);
                    return obj.userName || '';
                } catch (e) {
                    return '';
                }
            }''')

            if user_name:
                self._emit_log(f'获取到 accountName: {user_name}', 'general')
            else:
                self._emit_log('localStorage 中未找到 userName，accountName 取空', 'general')
            return user_name or ''
        except Exception as e:
            self._emit_log(f'获取 accountName 失败: {e}，取空', 'general')
            return ''

    def _build_report_status_info(self, results: list[dict], now_str: str) -> dict:
        targets = [
            {'name': r['url'], 'ok': r['ok'], 'error': r.get('error')}
            for r in results
        ]
        all_ok = bool(targets) and all(t['ok'] for t in targets)
        any_ok = any(t['ok'] for t in targets)
        errors = [f'{t["name"]}:{t["error"]}' for t in targets if not t['ok']]
        info = {
            'ok': all_ok,
            'partial': any_ok and not all_ok,
            'time': now_str,
            'targets': targets,
        }
        if errors:
            info['error'] = ', '.join(errors)
        return info

    async def _do_collect_and_report(self, context):
        """仅执行 Cookie 采集和上报，不做 session 检测和 reload"""
        self._emit_log('=== 开始采集上报 ===', 'report')
        try:
            payloads = await collect_cookies(context)
            self._emit_log(f'Cookie 采集完成: {len(payloads)} 条待上报', 'report')

            # 记录配置中关注的 cookie 获取时间（用于预判刷新）
            self._record_cookie_obtained_time(payloads)

            if not payloads:
                # 构建完整的未命中状态
                report_status = {}
                for item in EXPECTED_REPORT_ITEMS:
                    report_status[item['label']] = {'ok': False, 'error': '未采集到', 'time': datetime.now().strftime('%H:%M:%S')}
                self._emit_status({'sync': '无 Cookie 可上报', 'report_status': report_status})
                self._emit_log('采集到 0 条 Cookie，无数据上报', 'report')
                return

            self._emit_log(f'开始上报 {len(payloads)} 条 Cookie...', 'report')
            account_name = await self._get_account_name()
            extra_params = {'isScript': '1', 'accountName': account_name}
            reports = await report_cookies(payloads, emit_log=self._emit_log, extra_params=extra_params)

            now_str = datetime.now().strftime('%H:%M:%S')
            report_status = {}

            for entry in reports:
                cookie_str = entry['cookie']
                label = self._resolve_cookie_label(cookie_str)
                info = self._build_report_status_info(entry['results'], now_str)
                report_status[label] = info
                if info['ok']:
                    self._emit_log(f'✓ {label} 上报成功', 'report')
                elif info.get('partial'):
                    self._emit_log(f'⚠ {label} 部分上报成功 → {info.get("error", "")}', 'report')
                else:
                    self._emit_log(f'✗ {label} 上报失败 → {info.get("error", "")}', 'report')

            # 补充未采集到的项目（在 EXPECTED_REPORT_ITEMS 中但不在 payloads 中的）
            for item in EXPECTED_REPORT_ITEMS:
                if item['label'] not in report_status:
                    report_status[item['label']] = {'ok': False, 'error': '未采集到', 'time': now_str}

            total_missing = sum(1 for v in report_status.values() if v.get('error') == '未采集到')
            total_success = sum(1 for v in report_status.values() if v['ok'])
            total_partial = sum(1 for v in report_status.values() if v.get('partial'))
            total_fail = sum(1 for v in report_status.values() if not v['ok'] and not v.get('partial') and v.get('error') != '未采集到')

            self._emit_status({'report_status': report_status})

            summary_parts = [f'成功{total_success}']
            if total_partial > 0:
                summary_parts.append(f'部分成功{total_partial}')
            if total_fail > 0:
                summary_parts.append(f'失败{total_fail}')
            if total_missing > 0:
                summary_parts.append(f'未采集{total_missing}')

            self._emit_status({'sync': f'{"/".join(summary_parts)} ({now_str})'})
            self._emit_log(f'=== 上报完成: {"/".join(summary_parts)} ===', 'report')
        except Exception as e:
            self._emit_status({'sync': f'上报失败: {e}'})
            self._emit_log(f'采集上报异常: {e}', 'report')

    def _record_cookie_obtained_time(self, payloads: list[str]):
        for rule in self._proactive_refresh_rules:
            cookie_name = rule['cookie_name']
            for payload in payloads:
                if payload.startswith(f'{cookie_name}=') or f';{cookie_name}=' in payload:
                    if cookie_name not in self._cookie_obtained_at:
                        self._cookie_obtained_at[cookie_name] = time.time()
                        self._emit_log(f'[预判] 记录 {cookie_name} 获取时间', 'report')
                    break

    def _check_proactive_refresh_due(self, now: float) -> bool:
        for rule in self._proactive_refresh_rules:
            cookie_name = rule['cookie_name']
            ttl_seconds = rule.get('ttl_hours', 12) * 3600
            advance_seconds = rule.get('advance_minutes', 10) * 60

            obtained_at = self._cookie_obtained_at.get(cookie_name)
            if obtained_at is None:
                continue

            refresh_at = obtained_at + ttl_seconds - advance_seconds
            if now >= refresh_at:
                self._emit_log(
                    f'[预判] {cookie_name} 即将过期，触发预判刷新 '
                    f'(获取于 {int((now - obtained_at) / 3600)}h{int((now - obtained_at) % 3600 / 60)}m 前)',
                    'report',
                )
                return True
        return False

    async def _do_proactive_refresh(self, context):
        """预判刷新：删除即将过期的 cookie，然后走正常同步流程"""
        for rule in self._proactive_refresh_rules:
            cookie_name = rule['cookie_name']
            obtained_at = self._cookie_obtained_at.get(cookie_name)
            if obtained_at is None:
                continue

            ttl_seconds = rule.get('ttl_hours', 12) * 3600
            advance_seconds = rule.get('advance_minutes', 10) * 60
            now = time.time()

            if now >= obtained_at + ttl_seconds - advance_seconds:
                self._emit_log(f'[预判] 删除 cookie: {cookie_name}', 'report')
                await context.clear_cookies(name=cookie_name)
                self._cookie_obtained_at.pop(cookie_name, None)

        await self._do_sync_cycle(context)

    async def _do_sync_cycle(self, context):
        self._emit_status({'sync': '同步中...', 'heartbeat': '检测中...'})
        self._emit_log('=== 同步周期开始 ===', 'report')
        try:
            need_login = await self._check_session(context)
            if need_login:
                self._emit_status({'heartbeat': 'Session 过期'})
                self._emit_log('同步前检测: Session 过期，开始登录', 'login')
                login_ok = await self._do_login(context)
                if not login_ok:
                    self._emit_log('登录失败，本次同步中止', 'report')
                    self._emit_status({'sync': '登录失败，同步中止'})
                    return
                await self._open_persistent_pages(context)

            self._emit_log('开始 reload 常驻页面...', 'heartbeat')
            alive = await self._reload_persistent_pages(context)
            if not alive:
                self._emit_status({'heartbeat': 'Session 过期'})
                self._emit_log('reload 检测到 Session 过期，重新登录', 'heartbeat')
                login_ok = await self._do_login(context)
                if not login_ok:
                    self._emit_log('登录失败，本次同步中止', 'report')
                    self._emit_status({'sync': '登录失败，同步中止'})
                    return
                await self._open_persistent_pages(context)

            self._emit_status({'heartbeat': '正常'})
            self._emit_log('常驻页面 reload 完成', 'heartbeat')
            await self._do_collect_and_report(context)
        except Exception as e:
            self._emit_status({'sync': f'失败: {e}'})
            self._emit_log(f'同步周期异常: {e}', 'report')

    async def _do_heartbeat(self, context) -> bool:
        self._emit_status({'heartbeat': '检测中...'})
        try:
            alive = await self._reload_persistent_pages(context)
            if alive:
                self._emit_status({'heartbeat': '正常'})
                self._emit_log('心跳正常', 'heartbeat')
            else:
                self._emit_status({'heartbeat': 'Session 过期'})
                self._emit_log('心跳检测: Session 过期，需重新登录', 'heartbeat')
            return alive
        except Exception as e:
            self._emit_status({'heartbeat': f'异常: {e}'})
            self._emit_log(f'心跳异常: {e}', 'heartbeat')
            return False

    def _resolve_cookie_label(self, cookie_prefix: str) -> str:
        # 组合规则优先判断（避免被单条规则的前缀先匹配走）
        if 'CFO_DOWNLOAD' in cookie_prefix:
            return 'CFO_DOWNLOAD 组合'
        if 'WD_SESSION' in cookie_prefix and 'TSID' in cookie_prefix:
            return 'WD_SESSION+TSID 组合'
        for prefix, label in COOKIE_REPORT_LABELS.items():
            if cookie_prefix.startswith(prefix):
                return label
        return cookie_prefix[:30]

    # ========== PDD 站点方法 ==========

    async def _init_pdd(self, browser):
        """初始化 PDD 站点（独立 context）"""
        settings = _load_settings()
        pdd_enabled = settings.get('pdd_enabled', False)
        pdd_account = settings.get('pdd_account', '')
        pdd_password = settings.get('pdd_password', '')

        if not pdd_enabled or not pdd_account:
            self._emit_log('PDD: 未启用或未配置账号，跳过', 'pdd')
            self._pdd = None
            return

        from sites.pdd import PddSiteDriver
        self._pdd = PddSiteDriver(
            account=pdd_account,
            password=pdd_password,
            emit_log=self._emit_log,
        )
        await self._pdd.create_context(browser)

        session_ok = await self._pdd.check_session()
        if not session_ok:
            login_ok = await self._pdd.login()
            if not login_ok:
                self._emit_log('PDD: 启动登录失败，后续定时重试', 'pdd')
                return

        self._emit_log('PDD: 初始化完成，执行首次采集上报', 'pdd')
        await self._do_pdd_collect_and_report()

    async def _do_pdd_sync_cycle(self):
        """PDD 的采集-上报周期：常驻页面 reload 检测 session + 采集 cookie"""
        if not self._pdd:
            return
        try:
            self._emit_log('PDD: === 同步周期开始 ===', 'pdd')
            session_ok = await self._pdd.check_session()
            if not session_ok:
                self._emit_log('PDD: Session 过期，重新登录', 'pdd')
                if not await self._pdd.login():
                    self._emit_log('PDD: 登录失败，本次同步跳过', 'pdd')
                    self._emit_status({'pdd_status': {'SUB_PASS_ID (PDD)': {'ok': False, 'error': '登录失败', 'time': datetime.now().strftime('%H:%M:%S')}}})
                    return
                # 登录成功后页面已在目标页，等待 API 请求完成
                await asyncio.sleep(3)

            await self._do_pdd_collect_and_report()
        except Exception as e:
            self._emit_log(f'PDD: 同步异常: {e}', 'pdd')

    async def _do_pdd_collect_and_report(self):
        """PDD 采集并上报"""
        if not self._pdd:
            return
        now_str = datetime.now().strftime('%H:%M:%S')
        payloads = await self._pdd.collect()
        if not payloads:
            self._emit_status({'pdd_status': {'SUB_PASS_ID (PDD)': {'ok': False, 'error': '未采集到', 'time': now_str}}})
            return

        account_name = await self._get_account_name()
        extra_params = {'isScript': '1', 'accountName': account_name}
        reports = await report_cookies(payloads, emit_log=self._emit_log, log_category='pdd', extra_params=extra_params)
        for entry in reports:
            info = self._build_report_status_info(entry['results'], now_str)
            if info['ok']:
                self._emit_log('PDD: ✓ SUB_PASS_ID 上报成功', 'pdd')
                self._emit_status({'pdd_status': {'SUB_PASS_ID (PDD)': info}})
            elif info.get('partial'):
                self._emit_log(f'PDD: ⚠ SUB_PASS_ID 部分上报成功 → {info.get("error", "")}', 'pdd')
                self._emit_status({'pdd_status': {'SUB_PASS_ID (PDD)': info}})
            else:
                self._emit_log(f'PDD: ✗ SUB_PASS_ID 上报失败 → {info.get("error", "")}', 'pdd')
                self._emit_status({'pdd_status': {'SUB_PASS_ID (PDD)': info}})
        self._emit_log('PDD: === 同步周期结束 ===', 'pdd')

    def trigger_sync(self):
        self._manual_sync_event.set()

    def trigger_login(self):
        self._manual_login_event.set()

    def pause(self):
        self._paused = True
        self._emit_log('已暂停定时任务', 'general')

    def resume(self):
        self._paused = False
        self._emit_log('已恢复定时任务', 'general')

    def update_intervals(self, collect_min: int, heartbeat_min: int):
        self._collect_interval = collect_min
        self._heartbeat_interval = heartbeat_min
        self._emit_log(f'间隔已更新: 采集={collect_min}分钟, 心跳={heartbeat_min}分钟', 'general')

    def stop(self):
        self._stop_event.set()

    def _emit_log(self, msg: str, category: str = 'general'):
        ts = datetime.now().strftime('%H:%M:%S')
        self.signals.log_message.emit(f'{ts} {msg}', category)
        logger.opt(depth=1).info(msg)

    def _emit_status(self, data: dict):
        self.signals.status_update.emit(data)
