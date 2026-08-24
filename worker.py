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
    WANGDIAN_ANNOUNCEMENT_CLOSE_SELECTOR,
    WANGDIAN_INDEX_URL,
    WANGDIAN_MAP_AREA_DETAIL_URL_MARKER,
    WANGDIAN_NAV_SELECTOR,
    WANGDIAN_SEARCH_FIRST_RESULT_SELECTOR,
    WANGDIAN_SEARCH_INPUT_FALLBACK_SELECTOR,
    WANGDIAN_SEARCH_INPUT_SELECTOR,
    WANGDIAN_SEARCH_KEYWORDS,
    WANGDIAN_TRIGGER_INTERVAL_SECONDS,
    ZC_ENGINE_SID_INTERVAL_MINUTES,
    ZC_ORIGIN,
    ZC_REPORT_KEY,
    ZC_SEARCH_KEYWORD,
    ZC_SESSION_STORAGE_KEY,
    is_auth_url,
    is_logged_in_url,
)
from cookie_collector import build_wangdian_kfsd_payload, collect_cookies, EXPECTED_REPORT_ITEMS
from cookie_reporter import report_cookies
from login import login_via_dingtalk, wait_for_wangdian_entry_or_role


def _url_host(url: str) -> str:
    """取 URL 的 host 段（用于判断刷新前后是否跨域跳转）。"""
    try:
        return url.split('//', 1)[1].split('/', 1)[0].split('?', 1)[0]
    except Exception:
        return ''


def _is_finance_page(url: str) -> bool:
    """finance-mng 页面（finance-mng.sto.cn / finance-fundmanage.sto.cn 为同一后端别名）。"""
    return 'finance-mng.sto.cn' in url or 'finance-fundmanage.sto.cn' in url


COOKIE_REPORT_LABELS = {
    'SESSION=': 'SESSION (finance-mng)',
    'cod=': 'cod (market-cod)',
    'finance=': 'finance (finance-fundmanage)',
    'fin_report_session=': 'fin_report_session (finance-report)',
    'spf_sid=': 'spf_sid (wutonggateway)',
    'stoToken=': 'stoToken (wutonggateway)',
    'sid_cfo=': 'sid_cfo (wutonggateway)',
    'WD_SESSION=': 'WD_SESSION (wutonggateway)',
    'KFSD=': 'KFSD (wangdian全量)',
    'CFO_DOWNLOAD': 'CFO_DOWNLOAD 组合',
    'WD_STO=': 'WD_STO 组合',
    'TOKEN=': 'TOKEN (page.sto.cn)',
}

ZC_STATUS_LABEL = 'engineSid (客户经营分析)'


def _load_settings() -> dict:
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
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
        self._known_spf_sid_values: set[str] = set()
        self._wangdian_search_lock = None
        self._login_lock = None
        self._zc_page = None
        # 登录协调：登录是破坏性全局操作（clear_cookies + 关页），
        # 置 True 期间所有探测协程必须让路，避免用失效引用/脏 cookie 操作
        self._maintaining = False
        # 探测 page 提升为实例属性，便于登录时主动关闭使其下轮重建
        self._spf_probe_page = None
        # 探测协程 task 引用，用于 stop 时 cancel / 等待退出
        self._spf_probe_task = None
        self._engine_sid_task = None
        self._pdd_task = None
        # PDD 最近一次上报是否成功，用于合并状态计数（替代无条件 +1）
        self._pdd_last_ok = None

        settings = _load_settings()
        # 从持久化恢复已知 spf_sid 值（用于跨重启检测值变化）
        saved = settings.get('known_spf_sid_values', [])
        if saved:
            self._known_spf_sid_values.update(saved)
        self._collect_interval = settings.get('collect_interval', COLLECT_INTERVAL_MINUTES)
        self._heartbeat_interval = settings.get('heartbeat_interval', HEARTBEAT_INTERVAL_MINUTES)
        self._countdown_from_start = settings.get('countdown_from_start', False)
        self._proactive_refresh_rules = settings.get('proactive_refresh', [])
        self._cookie_obtained_at: dict[str, tuple[str, float]] = {}
        self._zc_enabled = settings.get('zc_enabled', True)
        self._zc_interval = settings.get('zc_interval', ZC_ENGINE_SID_INTERVAL_MINUTES)

    @property
    def collect_interval(self):
        return self._collect_interval

    @property
    def heartbeat_interval(self):
        return self._heartbeat_interval

    @property
    def zc_interval(self):
        return self._zc_interval

    @property
    def zc_enabled(self):
        return self._zc_enabled

    @property
    def is_paused(self):
        return self._paused

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

            context = await browser.new_context()

            # wangdian 首页搜索互斥锁：常驻页面搜索与 spf_sid 探测协程
            # 会同时操作 wangdian 首页搜索框，需串行避免冲突（Target crashed）
            self._wangdian_search_lock = asyncio.Lock()
            # 登录互斥锁：主循环（同步/心跳）与探测协程都可能触发重新登录，
            # 两个 _do_login 并发会互相 clear_cookies，导致登录全部失败
            self._login_lock = asyncio.Lock()

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
            last_heartbeat = time.time()

            # 启动 spf_sid 探测协程（独立 page，随机间隔 30s/1min/3min）
            self._spf_probe_task = asyncio.create_task(self._probe_spf_sid_loop(context))

            # 启动 engineSid 探测协程（独立 page + 独立时间线，默认每 30 分钟刷新上报）
            self._engine_sid_task = asyncio.create_task(self._probe_engine_sid_loop(context))

            # 启动 PDD 独立协程（独立时间线，不再阻塞主循环 5s tick）
            self._pdd_task = asyncio.create_task(self._probe_pdd_loop())

            while not self._stop_event.is_set():
                if self._paused:
                    self._emit_status({'paused': True})
                    await asyncio.sleep(5)
                    continue

                if self._manual_login_event.is_set():
                    self._manual_login_event.clear()
                    await self._do_login(context, force=True)
                    await self._open_persistent_pages(context)
                    # 手动登录后重置倒计时并触发一次采集，与手动同步行为一致
                    sync_start = time.time()
                    await self._do_collect_and_report(context)
                    last_sync = sync_start if self._countdown_from_start else time.time()
                    last_heartbeat = last_sync

                if self._manual_sync_event.is_set():
                    self._manual_sync_event.clear()
                    sync_start = time.time()
                    await self._do_sync_cycle(context)
                    last_sync = sync_start if self._countdown_from_start else time.time()
                    last_heartbeat = last_sync

                now = time.time()
                sync_due = (now - last_sync) >= self._collect_interval * 60
                heartbeat_due = (now - last_heartbeat) >= self._heartbeat_interval * 60
                proactive_due = self._check_proactive_refresh_due(now)

                if proactive_due:
                    sync_start = time.time()
                    await self._do_proactive_refresh(context)
                    last_sync = sync_start if self._countdown_from_start else time.time()
                    last_heartbeat = last_sync
                elif sync_due:
                    sync_start = time.time()
                    await self._do_sync_cycle(context)
                    last_sync = sync_start if self._countdown_from_start else time.time()
                    last_heartbeat = last_sync
                elif heartbeat_due:
                    heartbeat_start = time.time()
                    await self._do_heartbeat(context)
                    last_heartbeat = heartbeat_start if self._countdown_from_start else time.time()

                next_sync = max(0, self._collect_interval * 60 - (time.time() - last_sync))
                next_heartbeat = max(0, self._heartbeat_interval * 60 - (time.time() - last_heartbeat))
                self._emit_status({
                    'next_collect': int(next_sync),
                    'next_heartbeat': int(next_heartbeat),
                    'paused': False,
                })

                await asyncio.sleep(5)

            # 主循环退出，等待所有探测协程结束再关 browser，避免脏退出
            await self._await_probe_tasks()

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

    async def _do_login(self, context, *, force: bool = False):
        """重新登录（带互斥锁 + 维护态协调）：主循环与探测协程可能并发触发登录，
        两个 _do_login 并发会互相 clear_cookies 导致登录全部失败，
        因此用锁保证任意时刻只有一个登录流程在执行。
        _maintaining 标志让探测协程在登录期间让路，避免用到被清空的 cookie / 被关的 page。
        force=True 时绕过「已登录跳过」——用于 reload 已权威检测到某常驻页跳 SSO 的场景：
        该页可能是与 wangdian(WD_SESSION) 不同的独立会话（如 front.sto.cn / finance-mng
        走 sto-sso-web / sso.sto-express.cn），WD_SESSION 仍在不代表这些页面没过期，
        必须强制重登 + clear_cookies + 重开全部常驻页，否则旧页面/旧 cookie 原地保留。"""
        async with self._login_lock:
            # 已登录跳过：若其它流程刚登录成功，不再 clear_cookies 破坏其成果。
            # 但 force 时不跳过（reload 已证伪「已登录」）。
            if not force and await self._already_logged_in(context):
                self._emit_log('检测到已有有效登录，跳过重复登录', 'login')
                return True
            self._maintaining = True
            try:
                return await self._do_login_locked(context)
            finally:
                self._maintaining = False

    async def _do_login_locked(self, context):
        self._emit_status({'login': '登录中...'})
        # 关闭探测 page，使其下轮重建（cookie 即将被清空，旧 page 会失效）
        await self._close_probe_pages()
        # 清空 context 中所有 cookie，避免 _check_session 等前置操作
        # 留下的不完整 SSO cookie 干扰登录流程导致 403 重定向循环
        await context.clear_cookies()
        # 同时关闭所有常驻页面，否则 _open_persistent_pages 会因页面对象仍存在
        # 而跳过重新打开，导致登录后 cookie 无法重新生成
        await self._close_all_persistent_pages()
        # 清扫游离页签：历史多次重登/打开失败遗留的未登记页，运行久了会堆积几十个
        await self._close_orphan_pages(context)
        for attempt in range(3):
            self._emit_log(f'开始登录... (第{attempt+1}次)', 'login')
            page = await context.new_page()
            try:
                await login_via_dingtalk(page)
                await self._replace_login_page(page)
                now = datetime.now().strftime('%H:%M:%S')
                self._emit_status({'login': f'已登录 ({now})', 'login_time': now})
                self._emit_log('登录成功', 'login')
                return True
            except Exception as e:
                # 记录失败时的页面 URL 和关键 cookie，便于定位 403 循环根因
                try:
                    self._emit_log(f'[登录失败诊断] 当前 URL: {page.url}', 'login')
                    cookies = await context.cookies()
                    sto_names = sorted(c['name'] for c in cookies if 'sto.cn' in c.get('domain', ''))
                    wd_names = sorted(c['name'] for c in cookies if c.get('domain', '').endswith('wangdian.sto.cn'))
                    self._emit_log(f'[登录失败诊断] sto 域 cookie: {sto_names}', 'login')
                    self._emit_log(f'[登录失败诊断] wangdian 域 cookie: {wd_names}', 'login')
                except Exception as e2:
                    self._emit_log(f'[登录失败诊断] 采集诊断信息失败: {e2}', 'login')
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

    async def _already_logged_in(self, context) -> bool:
        """快速判断是否已登录：sto 域存在 WD_SESSION 视为已登录。
        用于避免并发触发的冗余登录 clear_cookies 破坏前一次登录成果。"""
        try:
            cookies = await context.cookies()
            return any(
                c['name'] == 'WD_SESSION' and 'sto.cn' in c.get('domain', '')
                for c in cookies
            )
        except Exception:
            return False

    async def _close_probe_pages(self):
        """关闭探测 page（spf_sid / engineSid），登录后强制重建，
        避免探测协程继续使用持有失效 cookie 的旧 page。"""
        for attr in ('_spf_probe_page', '_zc_page'):
            page = getattr(self, attr, None)
            if page and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass
            setattr(self, attr, None)

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
            # 虎盾后可能直接进入角色选择页，先处理
            try:
                from login import _select_first_role_and_enter
                if await _select_first_role_and_enter(page):
                    await page.wait_for_timeout(2000)
                    return
            except Exception as e:
                self._emit_log(f'角色选择处理异常: {e}', 'login')
            if not is_auth_url(page.url):
                return  # 已离开认证页，成功
            # 仍在认证页，检查是否有钉钉 iframe
            if not await _has_dingtalk_frame(page):
                await page.wait_for_timeout(3000)
                # 再次检查角色页
                try:
                    from login import _select_first_role_and_enter
                    if await _select_first_role_and_enter(page):
                        await page.wait_for_timeout(2000)
                        return
                except Exception as e:
                    self._emit_log(f'角色选择处理异常: {e}', 'login')
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
            # 等待页面离开 SSO，期间处理角色选择页（不要求进入 wangdian，只要不在 SSO 就行）
            for _ in range(30):
                await page.wait_for_timeout(1000)
                # 角色选择页通用处理（适用于任何站点的独立 SSO 页面）
                try:
                    from login import _select_first_role_and_enter
                    if await _select_first_role_and_enter(page):
                        await page.wait_for_timeout(2000)
                        continue
                except Exception as e:
                    self._emit_log(f'角色选择处理异常: {e}', 'login')
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
        login_ok = await self._do_login(context, force=True)
        if not login_ok:
            self._emit_status({'login': '登录失败', 'sync': '等待登录'})
            self._emit_log('单点登录未完成，禁止访问业务页和上报 Cookie', 'login')
            return False
        return True

    async def _dismiss_announcement(self, page, log_category: str = 'general'):
        try:
            close_btn = page.locator(WANGDIAN_ANNOUNCEMENT_CLOSE_SELECTOR).first
            if await close_btn.is_visible(timeout=3000):
                await close_btn.click()
                await page.wait_for_timeout(500)
                self._emit_log('公告弹窗已关闭', log_category)
        except Exception:
            pass

    async def _get_wangdian_search_input(self, page):
        primary = page.locator(WANGDIAN_SEARCH_INPUT_SELECTOR).first
        try:
            await primary.wait_for(state='visible', timeout=3000)
            return primary
        except Exception:
            fallback = page.locator(WANGDIAN_SEARCH_INPUT_FALLBACK_SELECTOR).first
            await fallback.wait_for(state='visible', timeout=5000)
            return fallback

    async def _is_wangdian_search_ready(self, page) -> bool:
        try:
            search_input = await self._get_wangdian_search_input(page)
            return await search_input.is_visible() and await search_input.is_enabled()
        except Exception:
            return False

    async def _ensure_wangdian_search_ready(self, page, log_category: str = 'general'):
        await page.bring_to_front()
        if await self._is_wangdian_search_ready(page):
            return
        self._emit_log('搜索框不可用，导航到 wangdian/index', log_category)
        await page.goto(WANGDIAN_INDEX_URL, wait_until='domcontentloaded', timeout=15000)
        await page.wait_for_timeout(2000)
        await self._dismiss_announcement(page, log_category)

    async def _search_and_click(self, page, keyword: str, log_category: str = 'general') -> bool:
        try:
            await page.bring_to_front()
            search_input = await self._get_wangdian_search_input(page)
            await search_input.wait_for(state='visible', timeout=5000)
            await search_input.click(timeout=5000)
            await page.keyboard.press('Escape')
            await page.wait_for_timeout(200)
            await search_input.fill('')
            await page.wait_for_timeout(300)
            await search_input.fill(keyword)
            self._emit_log(f'搜索框已输入「{keyword}」，等待联想框出现...', log_category)

            matched_result = page.locator(WANGDIAN_SEARCH_FIRST_RESULT_SELECTOR).filter(has_text=keyword).first
            await matched_result.wait_for(state='visible', timeout=8000)
            self._emit_log(f'联想框已出现，点击匹配「{keyword}」的结果...', log_category)
            await matched_result.click()
            await page.wait_for_timeout(2000)
            self._emit_log(f'搜索「{keyword}」点击完成，当前 URL: {page.url}', log_category)
            return True
        except Exception as e:
            self._emit_log(f'搜索「{keyword}」失败: {e}', log_category)
            return False

    async def _open_finance_fundmanage_page(self, context, log_category: str = 'general'):
        old_page = self._persistent_pages.get(FINANCE_FUNDMANAGE_URL)
        if old_page and not old_page.is_closed():
            await old_page.close()
        fm_page = await context.new_page()
        await fm_page.goto(FINANCE_FUNDMANAGE_URL, wait_until='domcontentloaded', timeout=15000)
        await fm_page.wait_for_timeout(2000)
        self._persistent_pages[FINANCE_FUNDMANAGE_URL] = fm_page
        self._emit_log(f'常驻页面已打开: {FINANCE_FUNDMANAGE_URL}', log_category)

    async def _run_wangdian_searches(self, context, page, *, open_finance_fundmanage: bool = False, log_category: str = 'general'):
        """在 wangdian/index 依次搜索 WANGDIAN_SEARCH_KEYWORDS，触发对应 Cookie 生成。
        与 spf_sid 探测协程互斥（同一把锁），避免同时操作 wangdian 首页搜索框导致冲突。"""
        async with self._wangdian_search_lock:
            await self._run_wangdian_searches_locked(
                context, page,
                open_finance_fundmanage=open_finance_fundmanage,
                log_category=log_category,
            )

    async def _run_wangdian_searches_locked(self, context, page, *, open_finance_fundmanage: bool = False, log_category: str = 'general'):
        """wangdian 搜索具体实现（调用方需已持有 _wangdian_search_lock）"""
        await self._ensure_wangdian_search_ready(page, log_category)
        await self._dismiss_announcement(page, log_category)

        failed_keywords: list[str] = []
        for keyword in WANGDIAN_SEARCH_KEYWORDS:
            if not await self._search_and_click(page, keyword, log_category):
                failed_keywords.append(keyword)

        for keyword in failed_keywords[:]:
            self._emit_log(f'重试搜索「{keyword}」...', log_category)
            if await self._search_and_click(page, keyword, log_category):
                failed_keywords.remove(keyword)

        total = len(WANGDIAN_SEARCH_KEYWORDS)
        success_count = total - len(failed_keywords)
        self._emit_log(f'wangdian 搜索完成: {success_count}/{total}', log_category)
        if failed_keywords:
            self._emit_log(f'wangdian 搜索未成功: {", ".join(failed_keywords)}', log_category)

        if open_finance_fundmanage:
            fm_page = self._persistent_pages.get(FINANCE_FUNDMANAGE_URL)
            if not fm_page or fm_page.is_closed():
                try:
                    await self._open_finance_fundmanage_page(context, log_category)
                except Exception as e:
                    self._emit_log(f'finance-fundmanage 页面打开失败: {e}', log_category)

    async def _maybe_run_wangdian_searches(self, context, *, open_finance_fundmanage: bool = False, log_category: str = 'general'):
        """全部常驻页就绪后，在 wangdian/index 执行搜索触发"""
        wangdian_page = self._persistent_pages.get(WANGDIAN_INDEX_URL)
        if not wangdian_page or wangdian_page.is_closed() or is_auth_url(wangdian_page.url):
            return
        self._emit_log('执行 wangdian 搜索触发 Cookie 生成', log_category)
        try:
            await self._run_wangdian_searches(
                context,
                wangdian_page,
                open_finance_fundmanage=open_finance_fundmanage,
                log_category=log_category,
            )
        except Exception as e:
            self._emit_log(f'wangdian 搜索失败: {e}', log_category)

    async def _open_one_persistent_page(self, context, url: str, log_category: str = 'general') -> bool:
        page = None
        try:
            page = await context.new_page()
            await page.goto(url, wait_until='domcontentloaded', timeout=15000)
            await page.wait_for_timeout(2000)
            self._emit_log(f'常驻页面导航完成，当前 URL: {page.url}', log_category)

            if is_auth_url(page.url):
                # TODO: 实操中心暂不需要（TOKEN 由订单查询页产生），需要时恢复以下分支：
                # if 'page.sto.cn' in url:
                #     self._emit_log(f'page.sto.cn 需要独立登录，执行登录流程', 'login')
                #     try:
                #         await self._do_sso_login_on_page(page)
                #         await page.wait_for_timeout(3000)
                #         if url not in page.url:
                #             await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                #             await page.wait_for_timeout(3000)
                #         token_ok = await self._ensure_page_sto_token(page)
                #         self._emit_log(f'page.sto.cn 登录完成，TOKEN 生成: {token_ok}，当前 URL: {page.url}', 'login')
                #     except Exception as e:
                #         self._emit_log(f'page.sto.cn 登录失败: {e}，跳过此页面', 'login')
                #         await page.close()
                #         return False
                if 'market-cod.sto.cn' in url:
                    # market-cod 有独立 session，当前页面已经在 SSO 页
                    self._emit_log(f'market-cod 需要独立登录，执行登录流程', 'login')
                    try:
                        await self._do_sso_login_on_page(page)
                        await page.wait_for_timeout(2000)
                        # 登录后跳转到 /cod/home/index，需要再次导航到目标页
                        if 'topayment/siteOrder/list' not in page.url:
                            self._emit_log(f'market-cod 登录后跳转到: {page.url}，再次导航到目标页', log_category)
                            await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                            await page.wait_for_timeout(2000)
                        self._emit_log(f'market-cod 登录完成，当前 URL: {page.url}', 'login')
                    except Exception as e:
                        self._emit_log(f'market-cod 登录失败: {e}', 'login')
                        await page.close()
                        return False
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
                        return False

            self._persistent_pages[url] = page
            self._emit_log(f'常驻页面已打开: {url}', log_category)
            return True
        except Exception as e:
            self._emit_log(f'常驻页面打开失败: {url} -> {e}', log_category)
            # 关闭已创建但未登记的页面（goto 超时等），避免页签泄漏
            if page is not None and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass
            return False

    async def _ensure_persistent_pages(self, context, log_category: str = 'heartbeat'):
        """对照 PERSISTENT_PAGES 补齐未登记的常驻页（如启动时打开失败被跳过的页面）"""
        for url in PERSISTENT_PAGES:
            if url in self._persistent_pages:
                continue
            self._emit_log(f'常驻页面未登记，尝试补开: {url}', log_category)
            await self._open_one_persistent_page(context, url, log_category)

    async def _close_all_persistent_pages(self):
        """关闭所有常驻页面，使 _open_persistent_pages 能重新打开（登录后 cookie 重新生成）"""
        for url in list(self._persistent_pages.keys()):
            page = self._persistent_pages.pop(url, None)
            if page:
                try:
                    if not page.is_closed():
                        await page.close()
                except Exception:
                    pass

    async def _close_orphan_pages(self, context):
        """关闭未被任何追踪器登记的游离页签（开新页异常/旧登录遗留等导致），防止页签堆积。
        重登是天然重置点：此时探测页与常驻页都已关闭，仅 _login_page 由登录流程管理，
        其余一律视为游离页清理。在 _do_login_locked 内 _close_all_persistent_pages 之后调用。"""
        tracked = set()
        for p in self._persistent_pages.values():
            tracked.add(id(p))
        for attr in ('_spf_probe_page', '_zc_page', '_login_page'):
            p = getattr(self, attr, None)
            if p is not None:
                tracked.add(id(p))
        closed = 0
        for p in list(context.pages):
            if id(p) in tracked or p.is_closed():
                continue
            try:
                await p.close()
                closed += 1
            except Exception:
                pass
        if closed:
            self._emit_log(f'已清理 {closed} 个游离页签', 'login')

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
            await self._open_one_persistent_page(context, url, 'general')
        # 关闭 _do_login 遗留的登录页面
        await self._close_login_page()
        fm_page = self._persistent_pages.get(FINANCE_FUNDMANAGE_URL)
        await self._maybe_run_wangdian_searches(
            context,
            open_finance_fundmanage=not fm_page or fm_page.is_closed(),
            log_category='general',
        )
        self._emit_log(f'常驻页面打开完成，共 {len(self._persistent_pages)} 个', 'general')

    async def _reload_persistent_pages(self, context) -> bool:
        session_expired = False
        await self._ensure_persistent_pages(context, log_category='heartbeat')
        self._emit_log(f'reload 常驻页面: {len(self._persistent_pages)} 个', 'heartbeat')
        for url, page in list(self._persistent_pages.items()):
            try:
                if page.is_closed():
                    self._emit_log(f'常驻页面已关闭，重新打开: {url}', 'heartbeat')
                    page = await context.new_page()
                    await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                    self._persistent_pages[url] = page
                    pre_url = page.url
                else:
                    self._emit_log(f'reload: {url}', 'heartbeat')
                    # 刷新前记录 URL / host，用于刷新后比对（跨域跳转即视为过期）
                    pre_url = page.url
                    await page.reload(wait_until='domcontentloaded', timeout=15000)
                pre_host = _url_host(pre_url)

                # finance-mng 为 SPA（sto-js-web），session 过期走客户端 JS 慢重定向，
                # 固定 2s 往往读不到跳转，故对 finance 轮询最多 6s 捕获跳转。
                # 用 pre_url（实际页面 URL）判断：wangdian-rebate 常驻页的 key 是
                # wangdian.sto.cn，但 page.url 实际是 finance-mng.sto.cn/.../show.do。
                if _is_finance_page(pre_url) or _is_finance_page(url):
                    poll_deadline = time.monotonic() + 6
                    while time.monotonic() < poll_deadline:
                        await page.wait_for_timeout(500)
                        post_u = page.url
                        if is_auth_url(post_u) or _url_host(post_u) != pre_host:
                            break
                else:
                    await page.wait_for_timeout(2000)
                post_url = page.url
                self._emit_log(f'reload 后 URL: {post_url}', 'heartbeat')

                # chrome-error:// 页面无法恢复，直接抛异常走重新打开逻辑
                if 'chrome-error://' in post_url or 'about:blank' in post_url:
                    raise Exception(f'Page navigated to error: {post_url}')

                # 过期判定：① 跳到认证页；② 刷新后跨域（内容页 reload 后跳到其它 host，
                # 如 finance-mng → sso.sto-express.cn），用于兜住慢/未知 SSO 跳转。
                expired_now = is_auth_url(post_url) or (
                    _url_host(post_url) != pre_host and not is_auth_url(pre_url)
                )
                if expired_now:
                    # market-cod 有独立 session，跳转到 SSO 不代表全局过期
                    # （page.sto.cn 实操中心已暂不启用）
                    if 'market-cod.sto.cn' in url:
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
                            # page.sto.cn 登录后等待实操中心换取 TOKEN（实操中心已暂不启用）
                            # if 'page.sto.cn' in url:
                            #     await self._ensure_page_sto_token(page)
                            self._emit_log(f'独立 session 页面重新登录完成: {url}', 'heartbeat')
                        except Exception as e:
                            self._emit_log(f'独立 session 页面登录失败: {url} -> {e}', 'heartbeat')
                    else:
                        self._emit_log(f'常驻页面 reload 后跳转到登录页: {url} → {page.url}', 'heartbeat')
                        # 关闭停留在认证页的旧页面，以便 _open_persistent_pages 能重新打开
                        try:
                            if not page.is_closed():
                                await page.close()
                        except Exception:
                            pass
                        session_expired = True
                        break

            except Exception as e:
                self._emit_log(f'常驻页面 reload 失败: {url} -> {e}', 'heartbeat')
                # 先关闭本页（可能是 closed-branch 新建后 goto 失败的游离页），防止页签泄漏
                try:
                    if page is not None and not page.is_closed():
                        await page.close()
                except Exception:
                    pass
                # finance-fundmanage 需要通过 wangdian 搜索入口打开，不能直接 goto
                if FINANCE_FUNDMANAGE_URL in url:
                    self._emit_log(f'finance-fundmanage 需要通过搜索入口重新打开', 'heartbeat')
                    await self._reopen_finance_fundmanage(context)
                else:
                    new_page = None
                    try:
                        new_page = await context.new_page()
                        await new_page.goto(url, wait_until='domcontentloaded', timeout=15000)
                        self._persistent_pages[url] = new_page
                        self._emit_log(f'常驻页面重新打开成功: {url}', 'heartbeat')
                    except Exception as e2:
                        self._emit_log(f'常驻页面重新打开也失败: {url} -> {e2}', 'heartbeat')
                        # 关闭重新打开失败产生的游离页
                        if new_page is not None and not new_page.is_closed():
                            try:
                                await new_page.close()
                            except Exception:
                                pass

        await self._maybe_run_wangdian_searches(context, log_category='heartbeat')
        return not session_expired

    async def _reopen_finance_fundmanage(self, context):
        """finance-fundmanage reload 失败时，通过完整 wangdian 搜索后重新打开"""
        try:
            wangdian_page = self._persistent_pages.get(WANGDIAN_INDEX_URL)
            if not wangdian_page or wangdian_page.is_closed():
                wangdian_page = await context.new_page()
                await wangdian_page.goto(WANGDIAN_INDEX_URL, wait_until='domcontentloaded', timeout=15000)
                await wangdian_page.wait_for_timeout(2000)
                self._persistent_pages[WANGDIAN_INDEX_URL] = wangdian_page

            await self._run_wangdian_searches(
                context,
                wangdian_page,
                open_finance_fundmanage=True,
                log_category='heartbeat',
            )
            self._emit_log('finance-fundmanage 通过搜索入口重新打开成功', 'heartbeat')
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
            {'name': r['url'], 'env': r.get('env', 'unknown'), 'ok': r['ok'], 'error': r.get('error')}
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
        # 按环境聚合：正式 / 测试 各自是否全部成功（None 表示该环境无上报目标）
        prod_targets = [t for t in targets if t['env'] == 'prod']
        test_targets = [t for t in targets if t['env'] == 'test']
        info['prod_ok'] = all(t['ok'] for t in prod_targets) if prod_targets else None
        info['test_ok'] = all(t['ok'] for t in test_targets) if test_targets else None
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

            # D: 上报前校验 finance-mng 页面是否仍处于登录页（防止上报已死的旧 cookie）。
            # 仅对 finance-mng 页面做此校验；若其当前停在 SSO 登录页，说明 session 已过期，
            # 丢弃 SESSION(finance-mng) 这条过期 cookie，不再向上报（避免后端收到废 cookie）。
            finance_expired = False
            finance_page = self._persistent_pages.get(FINANCE_FUNDMANAGE_URL)
            if finance_page and not finance_page.is_closed() and is_auth_url(finance_page.url):
                self._emit_log('[上报校验] finance-mng 页面已跳转登录页，丢弃过期 SESSION(finance-mng) cookie，不上报', 'report')
                filtered = [p for p in payloads if self._resolve_cookie_label(p) != 'SESSION (finance-mng)']
                if len(filtered) != len(payloads):
                    payloads = filtered
                    finance_expired = True

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

            # D 续：finance-mng 因页面停在 SSO 被丢弃（未上报），标记为过期失败而非「未采集到」
            if finance_expired and 'SESSION (finance-mng)' not in report_status:
                report_status['SESSION (finance-mng)'] = {
                    'ok': False, 'error': 'session 过期（页面已跳转登录，未上报）', 'time': now_str,
                }

            # 补充未采集到的项目（在 EXPECTED_REPORT_ITEMS 中但不在 payloads 中的）
            for item in EXPECTED_REPORT_ITEMS:
                if item['label'] not in report_status:
                    report_status[item['label']] = {'ok': False, 'error': '未采集到', 'time': now_str}

            total_missing = sum(1 for v in report_status.values() if v.get('error') == '未采集到')
            total_success = sum(1 for v in report_status.values() if v['ok'])
            total_partial = sum(1 for v in report_status.values() if v.get('partial'))
            total_fail = sum(1 for v in report_status.values() if not v['ok'] and not v.get('partial') and v.get('error') != '未采集到')

            self._emit_status({'report_status': report_status, 'account': account_name})

            summary_parts = [f'成功{total_success}']
            if total_partial > 0:
                summary_parts.append(f'部分成功{total_partial}')
            if total_fail > 0:
                summary_parts.append(f'失败{total_fail}')
            if total_missing > 0:
                summary_parts.append(f'未采集{total_missing}')

            # 暂存 STO 部分的统计数据，等 PDD 上报完成后合并输出
            self._sto_summary = (total_success, total_partial, total_fail, total_missing, now_str)
            self._emit_log(f'=== 上报完成: {"/".join(summary_parts)} ===', 'report')
            # 如果没有 PDD，直接输出合并状态；否则等 PDD 完成后由 _do_pdd_collect_and_report 调用
            if not self._pdd:
                self._emit_combined_sync_status()
        except Exception as e:
            self._emit_status({'sync': f'上报失败: {e}'})
            self._emit_log(f'采集上报异常: {e}', 'report')

    def _emit_combined_sync_status(self):
        """合并 STO + PDD 的上报统计，输出统一的 sync 状态。"""
        if not hasattr(self, '_sto_summary') or self._sto_summary is None:
            return
        total_success, total_partial, total_fail, total_missing, now_str = self._sto_summary
        # 加上 PDD 的计数（按最近一次真实上报结果，不再无条件计成功）
        if self._pdd:
            if self._pdd_last_ok:
                total_success += 1
            elif self._pdd_last_ok is False:
                total_fail += 1
        summary_parts = [f'成功{total_success}']
        if total_partial > 0:
            summary_parts.append(f'部分成功{total_partial}')
        if total_fail > 0:
            summary_parts.append(f'失败{total_fail}')
        if total_missing > 0:
            summary_parts.append(f'未采集{total_missing}')
        self._emit_status({'sync': f'{"/".join(summary_parts)} ({now_str})'})

    def _record_cookie_obtained_time(self, payloads: list[str]):
        for rule in self._proactive_refresh_rules:
            cookie_name = rule['cookie_name']
            for payload in payloads:
                if payload.startswith(f'{cookie_name}=') or f';{cookie_name}=' in payload:
                    cookie_value = self._extract_cookie_value(payload, cookie_name)

                    if cookie_name not in self._cookie_obtained_at:
                        self._cookie_obtained_at[cookie_name] = (cookie_value, time.time())
                        self._emit_log(f'[预判] 首次记录 {cookie_name}', 'report')
                    else:
                        old_value, old_time = self._cookie_obtained_at[cookie_name]
                        if cookie_value != old_value:
                            self._cookie_obtained_at[cookie_name] = (cookie_value, time.time())
                            self._emit_log(f'[预判] {cookie_name} 值变化，重置倒计时', 'report')
                    break

    def _extract_cookie_value(self, payload: str, cookie_name: str) -> str:
        """从 payload 中提取指定 cookie 的值"""
        if payload.startswith(f'{cookie_name}='):
            return payload.split('=', 1)[1].split(';')[0]
        else:
            parts = payload.split(f';{cookie_name}=')
            if len(parts) > 1:
                return parts[1].split(';')[0]
        return ''

    def _check_proactive_refresh_due(self, now: float) -> bool:
        # TODO: 12h 预判已由 spf_sid 探测协程替代，待稳定后清理此方法
        return False
        for rule in self._proactive_refresh_rules:
            cookie_name = rule['cookie_name']
            ttl_seconds = rule.get('ttl_hours', 12) * 3600
            offset_seconds = rule.get('advance_minutes', 0) * 60

            record = self._cookie_obtained_at.get(cookie_name)
            if record is None:
                continue

            cookie_value, obtained_at = record
            refresh_at = obtained_at + ttl_seconds + offset_seconds
            if now >= refresh_at:
                elapsed = now - obtained_at
                value_preview = cookie_value[:8] + '...' if len(cookie_value) > 8 else cookie_value
                if offset_seconds >= 0:
                    self._emit_log(
                        f'[预判] {cookie_name} 已过期，触发刷新 '
                        f'(值: {value_preview}, 获取于 {int(elapsed / 3600)}h{int(elapsed % 3600 / 60)}m 前)',
                        'report',
                    )
                else:
                    self._emit_log(
                        f'[预判] {cookie_name} 即将过期（提前 {-rule.get("advance_minutes", 0)}m），触发刷新 '
                        f'(值: {value_preview}, 获取于 {int(elapsed / 3600)}h{int(elapsed % 3600 / 60)}m 前)',
                        'report',
                    )
                return True
        return False

    async def _do_proactive_refresh(self, context):
        """预判刷新（当前已禁用，由 spf_sid 探测协程替代）。"""
        # TODO: 12h 预判已由 spf_sid 探测协程替代，待稳定后清理此方法
        await self._do_sync_cycle(context)

    async def _recreate_probe_page(self, context, probe_page):
        """关闭并重建探测页面：probe_page 长时间运行或重登后可能 crash，
        goto 持续超时（Page.goto: Timeout），重建后恢复正常探测。"""
        if probe_page:
            try:
                if not probe_page.is_closed():
                    await probe_page.close()
            except Exception:
                pass
        return await context.new_page()

    async def _probe_spf_sid_loop(self, context):
        """spf_sid 探测协程：独立 page，随机间隔打开订单查询页面，
        检测 spf_sid 值变化。新值存储并触发上报，cookie 缺失则重新登录。
        登录维护态（_maintaining）期间让路，暂停（_paused）时跳过本轮。"""
        import random
        MAX_RETRIES = 3
        self._emit_log('[spf_sid探测] 协程启动', 'report')
        try:
            self._spf_probe_page = await context.new_page()
            while not self._stop_event.is_set():
                # 暂停或登录维护态期间让路，不操作 context
                if self._paused:
                    await asyncio.sleep(5)
                    continue
                if self._maintaining:
                    self._emit_log('[spf_sid探测] 登录维护中，跳过本轮', 'report')
                    await asyncio.sleep(5)
                    continue

                search_ok = False
                # 每轮开始确保探测页面可用（可能已被登录关闭 / 异常关闭或 crash）
                if self._spf_probe_page is None or self._spf_probe_page.is_closed():
                    self._spf_probe_page = await context.new_page()

                # 与主循环 wangdian 搜索互斥（同一把锁），避免同时操作首页搜索框
                async with self._wangdian_search_lock:
                    for attempt in range(1, MAX_RETRIES + 1):
                        try:
                            self._emit_log(f'[spf_sid探测] 第{attempt}次尝试...', 'report')
                            await self._spf_probe_page.goto(WANGDIAN_INDEX_URL, wait_until='domcontentloaded', timeout=15000)
                            await self._spf_probe_page.wait_for_timeout(2000)
                            await self._dismiss_announcement(self._spf_probe_page, 'spf_probe')
                            await self._search_and_click(self._spf_probe_page, '订单查询', 'spf_probe')
                            # 等待订单查询页加载完成（页面异步加载，接口响应后种下相关 cookie）
                            try:
                                await self._spf_probe_page.wait_for_load_state('networkidle', timeout=30000)
                                self._emit_log('[spf_sid探测] 订单查询页加载完成 (networkidle)', 'report')
                            except Exception:
                                # networkidle 超时（页面可能持续轮询），兜底等待
                                await self._spf_probe_page.wait_for_timeout(5000)
                                self._emit_log('[spf_sid探测] networkidle 超时，按固定等待处理', 'report')
                            search_ok = True
                            break
                        except Exception as e:
                            if attempt < MAX_RETRIES:
                                self._emit_log(f'[spf_sid探测] 搜索失败({attempt}/{MAX_RETRIES}): {e}，重建探测页面重试...', 'report')
                                self._spf_probe_page = await self._recreate_probe_page(context, self._spf_probe_page)
                            else:
                                self._emit_log(f'[spf_sid探测] 搜索全部失败({MAX_RETRIES}/{MAX_RETRIES}): {e}', 'report')

                if not search_ok:
                    self._emit_log(f'[spf_sid探测] 订单查询不可用，触发重新登录', 'report')
                    await self._spf_sid_handle_login(context)
                else:
                    cookies = await context.cookies()
                    spf = next((c for c in cookies if c['name'] == 'spf_sid'), None)

                    if not spf:
                        self._emit_log('[spf_sid探测] ✗ spf_sid 仍缺失，触发重新登录', 'report')
                        await self._spf_sid_handle_login(context)
                    else:
                        spf_value = spf['value']
                        if spf_value not in self._known_spf_sid_values:
                            self._emit_log(f'[spf_sid探测] ✓ 新 spf_sid (值: {spf_value[:8]}...)，存储并触发上报', 'report')
                            self._known_spf_sid_values.add(spf_value)
                            self._persist_known_spf_sid_values()
                            await self._do_collect_and_report(context)
                            self._emit_combined_sync_status()
                        else:
                            self._emit_log(f'[spf_sid探测] spf_sid 未变化，跳过', 'report')

                interval = random.choice([30, 60, 180])
                self._emit_log(f'[spf_sid探测] 下一轮探测在 {interval}s 后', 'report')
                await asyncio.sleep(interval)
        finally:
            if self._spf_probe_page and not self._spf_probe_page.is_closed():
                try:
                    await self._spf_probe_page.close()
                except Exception:
                    pass
            self._spf_probe_page = None
            self._emit_log('[spf_sid探测] 协程退出', 'report')

    async def _spf_sid_handle_login(self, context):
        """spf_sid 探测触发登录的统一处理：直接 await _do_login。
        _do_login 锁内已有「已登录跳过」保护，不会破坏其它流程刚完成的登录成果，
        从根上消除原来 _login_lock.locked() 预检查的 TOCTOU 竞态。"""
        try:
            login_ok = await self._do_login(context)
            if login_ok:
                await self._open_persistent_pages(context)
                # 重登已关闭 probe_page，这里确保重建
                if self._spf_probe_page is None or self._spf_probe_page.is_closed():
                    self._spf_probe_page = await context.new_page()
                self._known_spf_sid_values.clear()
                self._persist_known_spf_sid_values()
                await self._do_collect_and_report(context)
                self._emit_combined_sync_status()
            else:
                self._emit_log('[spf_sid探测] 登录失败，跳过本轮（下轮再检测）', 'report')
        except Exception as e2:
            self._emit_log(f'[spf_sid探测] 重新登录也失败: {e2}', 'report')

    def _persist_known_spf_sid_values(self):
        """将已知 spf_sid 值写入 settings.json，用于跨重启检测值变化。"""
        try:
            settings = _load_settings()
            settings['known_spf_sid_values'] = sorted(self._known_spf_sid_values)
            with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    async def _do_sync_cycle(self, context):
        self._emit_status({'sync': '同步中...', 'heartbeat': '检测中...'})
        self._emit_log('=== 同步周期开始 ===', 'report')
        try:
            need_login = await self._check_session(context)
            if need_login:
                self._emit_status({'heartbeat': 'Session 过期'})
                self._emit_log('同步前检测: Session 过期，开始登录', 'login')
                login_ok = await self._do_login(context, force=True)
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
                login_ok = await self._do_login(context, force=True)
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
                return True

            self._emit_status({'heartbeat': 'Session 过期'})
            self._emit_log('心跳检测: Session 过期，开始重新登录', 'heartbeat')
            login_ok = await self._do_login(context, force=True)
            if not login_ok:
                self._emit_log('心跳重登失败', 'heartbeat')
                return False
            await self._open_persistent_pages(context)
            self._emit_status({'heartbeat': '正常'})
            self._emit_log('心跳重登完成，开始采集上报', 'heartbeat')
            await self._do_collect_and_report(context)
            return True
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

    # ========== engineSid（客户经营分析）独立时间线 ==========

    async def _read_engine_sid(self, context) -> str:
        """遍历 context 内所有页面/子框架，在 origin 为 zc.sto.cn 处读 sessionStorage.engineSid。
        【客户经营分析】是在 wangdian 页面内以 iframe 方式打开的（不新开标签），
        engineSid 存在该 zc.sto.cn iframe 的 sessionStorage 里，故需遍历 frames。"""
        js = (
            "() => { try { return sessionStorage.getItem('%s') || ''; } "
            "catch (e) { return ''; } }" % ZC_SESSION_STORAGE_KEY
        )
        for page in context.pages:
            if page.is_closed():
                continue
            for frame in page.frames:
                if ZC_ORIGIN in frame.url:
                    try:
                        value = await frame.evaluate(js)
                        if value:
                            return value
                    except Exception:
                        pass
        return ''

    async def _read_engine_sid_with_wait(self, context, attempts: int = 20) -> str:
        """zc iframe 异步加载，engineSid 可能稍后才写入 sessionStorage，轮询等待。"""
        for _ in range(attempts):
            value = await self._read_engine_sid(context)
            if value:
                return value
            await asyncio.sleep(1)
        return ''

    async def _refresh_and_report_engine_sid(self, context):
        """独立探测页 goto wangdian/index → 搜索【客户经营分析】（同页 iframe 打开）→
        读取全新的 engineSid 并上报。engineSid 每次加载都变，不去重。"""
        now_str = datetime.now().strftime('%H:%M:%S')
        MAX_RETRIES = 3

        if self._zc_page is None or self._zc_page.is_closed():
            self._zc_page = await context.new_page()

        value = ''
        # 与其它 wangdian 搜索互斥，避免同时操作触发 Target crashed
        async with self._wangdian_search_lock:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    self._emit_log(f'[engineSid] 第{attempt}次尝试打开客户经营分析...', 'zc')
                    await self._zc_page.goto(WANGDIAN_INDEX_URL, wait_until='domcontentloaded', timeout=15000)
                    await self._zc_page.wait_for_timeout(2000)
                    await self._dismiss_announcement(self._zc_page, 'zc')
                    if not await self._search_and_click(self._zc_page, ZC_SEARCH_KEYWORD, 'zc'):
                        raise RuntimeError('搜索客户经营分析未点击成功')
                    # 等待 zc 业务系统 iframe 加载完成（异步写入 sessionStorage）
                    try:
                        await self._zc_page.wait_for_load_state('networkidle', timeout=30000)
                        self._emit_log('[engineSid] 客户经营分析页加载完成 (networkidle)', 'zc')
                    except Exception:
                        await self._zc_page.wait_for_timeout(5000)
                        self._emit_log('[engineSid] networkidle 超时，按固定等待处理', 'zc')
                    value = await self._read_engine_sid_with_wait(context)
                    if value:
                        break
                    self._emit_log(f'[engineSid] 第{attempt}次未从 zc.sto.cn 读到 engineSid', 'zc')
                except Exception as e:
                    self._emit_log(f'[engineSid] 第{attempt}次异常: {e}', 'zc')
                    # 探测页可能 crash，重建后重试
                    self._zc_page = await self._recreate_probe_page(context, self._zc_page)

        if not value:
            self._emit_log('[engineSid] ✗ 未取到 engineSid', 'zc')
            self._emit_status({'zc_status': {ZC_STATUS_LABEL: {'ok': False, 'error': '未采集到', 'time': now_str}}})
            return

        self._emit_log(f'[engineSid] ✓ 取到 engineSid (值: {value[:8]}...)，开始上报', 'zc')
        payload = f'{ZC_REPORT_KEY}={value}'
        account_name = await self._get_account_name()
        extra_params = {'isScript': '1', 'accountName': account_name}
        reports = await report_cookies([payload], emit_log=self._emit_log, log_category='zc', extra_params=extra_params)

        now_str = datetime.now().strftime('%H:%M:%S')
        for entry in reports:
            info = self._build_report_status_info(entry['results'], now_str)
            if info['ok']:
                self._emit_log('[engineSid] ✓ 上报成功', 'zc')
            elif info.get('partial'):
                self._emit_log(f'[engineSid] ⚠ 部分上报成功 → {info.get("error", "")}', 'zc')
            else:
                self._emit_log(f'[engineSid] ✗ 上报失败 → {info.get("error", "")}', 'zc')
            self._emit_status({'zc_status': {ZC_STATUS_LABEL: info}})

    async def _probe_engine_sid_loop(self, context):
        """engineSid 独立时间线：默认每 30 分钟刷新客户经营分析页并上报，间隔可在 GUI 实时修改。"""
        self._emit_log('[engineSid] 协程启动', 'zc')
        # 启动后稍等，等常驻页/登录就绪
        await asyncio.sleep(10)
        while not self._stop_event.is_set():
            if not self._zc_enabled:
                await asyncio.sleep(10)
                continue
            # 暂停或登录维护态期间让路
            if self._paused:
                await asyncio.sleep(5)
                continue
            if self._maintaining:
                self._emit_log('[engineSid] 登录维护中，跳过本轮', 'zc')
                await asyncio.sleep(5)
                continue
            try:
                await self._refresh_and_report_engine_sid(context)
            except Exception as e:
                self._emit_log(f'[engineSid] 周期异常: {e}', 'zc')

            target = max(1, self._zc_interval) * 60
            self._emit_log(f'[engineSid] 下一轮刷新在 {target}s 后', 'zc')
            waited = 0
            while waited < target and not self._stop_event.is_set() and self._zc_enabled:
                await asyncio.sleep(5)
                waited += 5
                target = max(1, self._zc_interval) * 60
        if self._zc_page and not self._zc_page.is_closed():
            try:
                await self._zc_page.close()
            except Exception:
                pass
        self._emit_log('[engineSid] 协程退出', 'zc')

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
            self._pdd_last_ok = False
            self._emit_status({'pdd_status': {'SUB_PASS_ID (PDD)': {'ok': False, 'error': '未采集到', 'time': now_str}}})
            self._emit_combined_sync_status()
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
        self._pdd_last_ok = info.get('ok', False) if reports else False
        self._emit_combined_sync_status()
        self._emit_log('PDD: === 同步周期结束 ===', 'pdd')

    async def _probe_pdd_loop(self):
        """PDD 独立时间线协程：按采集间隔定时 check_session + 采集上报。
        从主循环移出，避免 PDD 登录重试阻塞主循环 5s tick 和状态上报。
        暂停期间让路。"""
        if not self._pdd:
            return
        self._emit_log('PDD: 独立协程启动', 'pdd')
        # 首次稍等，和 STO 首次上报错开
        await asyncio.sleep(15)
        while not self._stop_event.is_set():
            if self._paused:
                await asyncio.sleep(5)
                continue
            try:
                await self._do_pdd_sync_cycle()
            except Exception as e:
                self._emit_log(f'PDD: 协程周期异常: {e}', 'pdd')
            # 按采集间隔等待，期间可响应停止 / 暂停
            target = max(1, self._collect_interval) * 60
            waited = 0
            while waited < target and not self._stop_event.is_set():
                await asyncio.sleep(5)
                waited += 5
        self._emit_log('PDD: 独立协程退出', 'pdd')

    async def _await_probe_tasks(self):
        """主循环退出后，cancel 并等待所有探测协程结束，再让 browser.close() 执行，
        避免协程仍持有 page 引用导致脏退出。"""
        tasks = [t for t in (self._spf_probe_task, self._engine_sid_task, self._pdd_task) if t]
        for t in tasks:
            if not t.done():
                t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

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

    def update_zc_settings(self, enabled: bool, interval_min: int):
        self._zc_enabled = enabled
        self._zc_interval = interval_min
        self._emit_log(f'engineSid 设置已更新: 启用={enabled}, 刷新间隔={interval_min}分钟', 'general')

    def stop(self):
        self._stop_event.set()

    def _emit_log(self, msg: str, category: str = 'general'):
        ts = datetime.now().strftime('%H:%M:%S')
        self.signals.log_message.emit(f'{ts} {msg}', category)
        logger.opt(depth=1).info(msg)

    def _emit_status(self, data: dict):
        self.signals.status_update.emit(data)
