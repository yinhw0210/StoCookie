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
    HEARTBEAT_INTERVAL_MINUTES,
    LOG_DIR,
    SETTINGS_PATH,
    SSO_URL,
    STORAGE_DIR,
    STORAGE_STATE_PATH,
    WANGDIAN_MAP_AREA_DETAIL_URL_MARKER,
    WANGDIAN_TRIGGER_INTERVAL_SECONDS,
    is_auth_url,
    is_logged_in_url,
)
from cookie_collector import build_wangdian_kfsd_payload, collect_cookies, visit_cookie_seed_pages
from cookie_reporter import report_cookies
from heartbeat import heartbeat
from login import login_via_dingtalk, wait_for_wangdian_entry_or_role

COOKIE_DOMAINS = ['finance-mng', 'market-cod', 'finance-fundmanage', 'wutonggateway', 'wangdian']


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
                self._emit_status({'sync': '等待同步'})
                self._emit_log('启动 SSO 校验完成，等待手动或定时 Cookie 同步', 'report')
            else:
                self._emit_status({'sync': '等待登录'})
                self._emit_log('启动登录未完成，跳过首次 Cookie 同步', 'report')

            last_collect = time.time()
            last_heartbeat = time.time()

            while not self._stop_event.is_set():
                if self._paused:
                    self._emit_status({'paused': True})
                    await asyncio.sleep(5)
                    continue

                if self._manual_login_event.is_set():
                    self._manual_login_event.clear()
                    await self._do_login(context)

                if self._manual_sync_event.is_set():
                    self._manual_sync_event.clear()
                    await self._do_collect(context)
                    last_collect = time.time()

                now = time.time()
                collect_due = (now - last_collect) >= self._collect_interval * 60
                heartbeat_due = (now - last_heartbeat) >= self._heartbeat_interval * 60

                if collect_due:
                    await self._do_collect(context)
                    last_collect = time.time()

                if heartbeat_due:
                    alive = await self._do_heartbeat(context)
                    if not alive:
                        await self._do_login(context)
                    last_heartbeat = time.time()

                next_collect = max(0, self._collect_interval * 60 - (time.time() - last_collect))
                next_heartbeat = max(0, self._heartbeat_interval * 60 - (time.time() - last_heartbeat))
                self._emit_status({
                    'next_collect': int(next_collect),
                    'next_heartbeat': int(next_heartbeat),
                    'paused': False,
                })

                await asyncio.sleep(5)

            await browser.close()

    async def _check_session(self, context) -> bool:
        page = await context.new_page()
        try:
            self._emit_log(f'访问登录入口检查 Session: {SSO_URL}', 'login')
            await page.goto(SSO_URL, wait_until='domcontentloaded', timeout=20000)
            await page.wait_for_timeout(3000)
            self._emit_log(f'登录入口检查完成，当前 URL: {page.url}', 'login')

            if is_logged_in_url(page.url):
                self._emit_log(f'Session 有效，网点入口未跳转认证页: {page.url}', 'login')
                return False

            if is_auth_url(page.url):
                self._emit_log(f'Session 未完成，网点入口已跳转认证页: {page.url}', 'login')
                return True

            try:
                await wait_for_wangdian_entry_or_role(page, timeout_ms=30000)
            except Exception as e:
                if is_auth_url(page.url):
                    self._emit_log(f'Session 未完成，仍在认证页: {page.url}', 'login')
                else:
                    self._emit_log(f'Session 未完成，未进入网点系统: {page.url} ({e})', 'login')
                return True

            if is_logged_in_url(page.url):
                self._emit_log(f'Session 有效，已进入网点系统: {page.url}', 'login')
                return False

            self._emit_log(f'Session 未完成，未进入网点系统: {page.url}', 'login')
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

    async def _do_collect(self, context, sso_checked: bool = False):
        self._emit_status({'sync': '同步中...'})
        try:
            if not sso_checked:
                login_ok = await self._ensure_logged_in(context, 'collect')
                if not login_ok:
                    self._emit_status({'sync': '等待登录'})
                    self._emit_log('登录未完成，跳过本轮 Cookie 同步', 'report')
                    return

            seed_results = await visit_cookie_seed_pages(context)
            seed_success = sum(1 for r in seed_results if r['ok'])
            seed_fail = len(seed_results) - seed_success
            self._emit_log(
                f'种子页面访问完成: 成功{seed_success}/失败{seed_fail}，继续采集已有 Cookie',
                'report',
            )
            for result in seed_results:
                if result['ok']:
                    self._emit_log(f'种子页成功: {result["url"]} -> {result["final_url"]}', 'report')
                else:
                    self._emit_log(
                        f'种子页跳过: {result["url"]} -> {result["reason"] or "未知原因"}',
                        'report',
                    )

            payloads = await collect_cookies(context)
            self._emit_log(f'Cookie payload 生成完成: {len(payloads)} 条', 'report')

            # 发送 Cookie 状态
            all_cookies = await context.cookies()
            cookie_status = {}
            for d in COOKIE_DOMAINS:
                cookie_status[d] = any(d in c.get('domain', '') for c in all_cookies)
            self._emit_status({'cookie_status': cookie_status})
            status_text = ' | '.join(f'{d}={"有" if ok else "无"}' for d, ok in cookie_status.items())
            self._emit_log(f'Cookie 域名状态: {status_text}', 'report')

            if not payloads:
                self._emit_status({'sync': '无 Cookie 可上报'})
                self._emit_log('采集到 0 条 Cookie，无数据上报', 'report')
                return

            reports = await report_cookies(payloads)

            # 逐条输出上报详情
            total_success = 0
            total_fail = 0
            for entry in reports:
                results_str = ' / '.join(
                    f'{r["url"]} ✓' if r['ok'] else f'{r["url"]} ✗({r["error"]})'
                    for r in entry['results']
                )
                self._emit_log(f'{entry["cookie"]}... → {results_str}', 'report')
                for r in entry['results']:
                    if r['ok']:
                        total_success += 1
                    else:
                        total_fail += 1

            now = datetime.now().strftime('%H:%M:%S')
            if total_fail > 0:
                self._emit_status({'sync': f'部分失败 ({now}, 成功{total_success}/失败{total_fail})'})
                self._emit_log(f'上报完成: {len(payloads)}条Cookie, 成功{total_success}/失败{total_fail}', 'report')
            else:
                self._emit_status({'sync': f'成功 ({now}, {len(payloads)}条)'})
                self._emit_log(f'上报完成: {len(payloads)}条Cookie, 全部成功({total_success}次)', 'report')
        except Exception as e:
            self._emit_status({'sync': f'失败: {e}'})
            self._emit_log(f'Cookie 同步异常: {e}', 'report')

    async def _do_heartbeat(self, context) -> bool:
        self._emit_status({'heartbeat': '检测中...'})
        try:
            need_login = await self._check_session(context)
            if need_login:
                self._emit_status({'heartbeat': 'Session 过期'})
                self._emit_log('心跳前置检测: Session 未完成，跳过业务页保活', 'heartbeat')
                return False

            alive = await heartbeat(context)
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
