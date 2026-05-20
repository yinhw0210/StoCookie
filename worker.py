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
)
from cookie_collector import collect_cookies
from cookie_reporter import report_cookies
from heartbeat import heartbeat
from login import login_via_dingtalk

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

            need_login = await self._check_session(context)
            if need_login:
                await self._do_login(context)
            else:
                self._emit_status({'login': '已登录'})
                self._emit_log('Session 有效，跳过登录', 'login')

            await self._do_collect(context)

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
            await page.goto(SSO_URL, wait_until='domcontentloaded', timeout=20000)
            # SSO_URL 本身含 sto-sso-web，如果 Session 有效会跳转走
            # 等待可能的跳转
            try:
                await page.wait_for_url(
                    lambda url: 'sto-sso-web' not in url,
                    timeout=10000,
                )
                self._emit_log(f'Session 有效，已跳转到: {page.url}', 'login')
                return False
            except Exception:
                # 超时未跳转，说明停留在登录页
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
                await page.close()
        return False

    async def _do_collect(self, context):
        self._emit_status({'sync': '同步中...'})
        try:
            payloads = await collect_cookies(context)

            # 发送 Cookie 状态
            all_cookies = await context.cookies()
            cookie_status = {}
            for d in COOKIE_DOMAINS:
                cookie_status[d] = any(d in c.get('domain', '') for c in all_cookies)
            self._emit_status({'cookie_status': cookie_status})

            # 0 条 Cookie 时主动检查 Session
            if not payloads:
                self._emit_log('采集到 0 条 Cookie，检查 Session 状态...', 'report')
                need_login = await self._check_session(context)
                if need_login:
                    login_ok = await self._do_login(context)
                    if login_ok:
                        payloads = await collect_cookies(context)
                        all_cookies = await context.cookies()
                        cookie_status = {d: any(d in c.get('domain', '') for c in all_cookies) for d in COOKIE_DOMAINS}
                        self._emit_status({'cookie_status': cookie_status})
                else:
                    self._emit_log('Session 有效但无 Cookie，可能业务页面未正常加载', 'report')

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
