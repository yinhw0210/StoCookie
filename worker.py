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
from cookie_collector import build_wangdian_kfsd_payload, collect_cookies
from cookie_reporter import report_cookies
from login import login_via_dingtalk, wait_for_wangdian_entry_or_role

COOKIE_DOMAINS = ['finance-mng', 'market-cod', 'finance-fundmanage', 'wutonggateway', 'wangdian']

COOKIE_REPORT_LABELS = {
    'SESSION=': 'finance-mng',
    'cod=': 'market-cod',
    'finance=': 'finance-fundmanage',
    'spf_sid=': 'wutonggateway(spf_sid)',
    'stoToken=': 'wutonggateway(stoToken)',
    'sid_cfo=': 'wutonggateway(sid_cfo)',
    'WD_SESSION=': 'wutonggateway(WD_SESSION)',
    'KFSD=': 'wangdian(KFSD)',
    'CFO_DOWNLOAD': 'wutonggateway(CFO组合)',
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

        settings = _load_settings()
        self._collect_interval = settings.get('collect_interval', COLLECT_INTERVAL_MINUTES)
        self._heartbeat_interval = settings.get('heartbeat_interval', HEARTBEAT_INTERVAL_MINUTES)

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
                self._emit_log('启动 SSO 校验完成，常驻页面已打开，等待定时 Cookie 同步', 'report')
            else:
                self._emit_status({'sync': '等待登录'})
                self._emit_log('启动登录未完成，跳过首次 Cookie 同步', 'report')

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
                    last_sync = time.time()

                now = time.time()
                sync_due = (now - last_sync) >= self._collect_interval * 60

                if sync_due:
                    await self._do_sync_cycle(context)
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

        # fallback: 新开页面检测
        page = await context.new_page()
        try:
            self._emit_log(f'新开页面访问登录入口检查 Session: {SSO_URL}', 'login')
            await page.goto(SSO_URL, wait_until='domcontentloaded', timeout=20000)
            await page.wait_for_timeout(3000)
            self._emit_log(f'登录入口检查完成，当前 URL: {page.url}', 'login')

            if is_logged_in_url(page.url):
                self._emit_log(f'Session 有效，网点入口未跳转认证页: {page.url}', 'login')
                return False

            if is_auth_url(page.url):
                self._emit_log(f'Session 过期，网点入口已跳转认证页: {page.url}', 'login')
                return True

            try:
                await wait_for_wangdian_entry_or_role(page, timeout_ms=30000)
            except Exception as e:
                if is_auth_url(page.url):
                    self._emit_log(f'Session 过期，仍在认证页: {page.url}', 'login')
                else:
                    self._emit_log(f'Session 状态不明，未进入网点系统: {page.url} ({e})', 'login')
                return True

            if is_logged_in_url(page.url):
                self._emit_log(f'Session 有效，已进入网点系统: {page.url}', 'login')
                return False

            self._emit_log(f'Session 状态不明，未进入网点系统: {page.url}', 'login')
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
            reports = await report_cookies([payload])
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
                    self._emit_log(f'常驻页面跳转到登录页，执行登录流程: {url}', 'login')
                    try:
                        await login_via_dingtalk(page)
                        await page.wait_for_timeout(2000)
                    except Exception as e:
                        self._emit_log(f'常驻页面登录失败: {url} -> {e}', 'login')
                        await page.close()
                        continue
                    if url not in page.url:
                        self._emit_log(f'登录后未重定向到目标页，手动导航: {url}', 'general')
                        await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                        await page.wait_for_timeout(2000)
                if 'wangdian.sto.cn/index' in url:
                    await self._handle_wangdian_index(context, page)
                self._persistent_pages[url] = page
                self._emit_log(f'常驻页面已打开: {url}', 'general')
            except Exception as e:
                self._emit_log(f'常驻页面打开失败: {url} -> {e}', 'general')
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
                    self._emit_log(f'常驻页面 reload 后跳转到登录页: {url} → {page.url}', 'heartbeat')
                    session_expired = True
                    break

                if 'wangdian.sto.cn/index' in url:
                    await self._dismiss_announcement(page)
            except Exception as e:
                self._emit_log(f'常驻页面 reload 失败: {url} -> {e}', 'heartbeat')
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
            self._emit_log('常驻页面 reload 完成，开始采集 Cookie', 'report')

            payloads = await collect_cookies(context)
            self._emit_log(f'Cookie 采集完成: {len(payloads)} 条', 'report')

            all_cookies = await context.cookies()
            cookie_status = {}
            for d in COOKIE_DOMAINS:
                cookie_status[d] = any(d in c.get('domain', '') for c in all_cookies)

            if not payloads:
                self._emit_status({'sync': '无 Cookie 可上报', 'cookie_status': cookie_status})
                self._emit_log('采集到 0 条 Cookie，无数据上报', 'report')
                return

            self._emit_log(f'开始上报 {len(payloads)} 条 Cookie...', 'report')
            reports = await report_cookies(payloads)

            now_str = datetime.now().strftime('%H:%M:%S')
            report_status = {}
            for entry in reports:
                cookie_str = entry['cookie']
                label = self._resolve_cookie_label(cookie_str)
                all_ok = all(r['ok'] for r in entry['results'])
                report_status[label] = {'ok': all_ok, 'time': now_str}
                if all_ok:
                    self._emit_log(f'✓ {label} 上报成功 ({now_str})', 'report')
                else:
                    errors = [f'{r["url"]}:{r["error"]}' for r in entry['results'] if not r['ok']]
                    self._emit_log(f'✗ {label} 上报失败 ({now_str}) → {", ".join(errors)}', 'report')

            total_success = sum(1 for v in report_status.values() if v['ok'])
            total_fail = sum(1 for v in report_status.values() if not v['ok'])

            self._emit_status({
                'cookie_status': cookie_status,
                'report_status': report_status,
            })

            if total_fail > 0:
                self._emit_status({'sync': f'部分失败 ({now_str}, 成功{total_success}/失败{total_fail})'})
                self._emit_log(f'=== 同步完成: {len(payloads)}条Cookie, 成功{total_success}/失败{total_fail} ===', 'report')
            else:
                self._emit_status({'sync': f'成功 ({now_str}, {len(payloads)}条)'})
                self._emit_log(f'=== 同步完成: {len(payloads)}条Cookie, 全部成功({total_success}次) ===', 'report')
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
        for prefix, label in COOKIE_REPORT_LABELS.items():
            if cookie_prefix.startswith(prefix):
                return label
        if 'WD_SESSION' in cookie_prefix and 'TSID' in cookie_prefix:
            if 'sid_cfo' in cookie_prefix:
                return 'wutonggateway(CFO组合)'
            return 'wutonggateway(WD+TSID组合)'
        return cookie_prefix[:30]

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
