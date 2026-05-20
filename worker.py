import asyncio
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
    SSO_URL,
    STORAGE_DIR,
    STORAGE_STATE_PATH,
)
from cookie_collector import collect_cookies
from cookie_reporter import report_cookies
from heartbeat import heartbeat
from login import login_via_dingtalk


class WorkerSignals(QObject):
    log_message = Signal(str)
    status_update = Signal(dict)


class BackgroundWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.signals = WorkerSignals()
        self._manual_sync_event = threading.Event()
        self._manual_login_event = threading.Event()
        self._stop_event = threading.Event()
        self._loop = None

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
            self._emit_log(f'后台线程异常退出: {e}')
        finally:
            self._loop.close()

    async def _async_main(self):
        from playwright.async_api import async_playwright

        self._emit_status({'login': '启动中...'})

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)

            if os.path.exists(STORAGE_STATE_PATH):
                self._emit_log('恢复已有 Session...')
                context = await browser.new_context(storage_state=STORAGE_STATE_PATH)
            else:
                self._emit_log('无已有 Session，创建新 context')
                context = await browser.new_context()

            need_login = await self._check_session(context)
            if need_login:
                await self._do_login(context)
            else:
                self._emit_status({'login': '已登录'})
                self._emit_log('Session 有效，跳过登录')

            await self._do_collect(context)

            last_collect = time.time()
            last_heartbeat = time.time()

            while not self._stop_event.is_set():
                if self._manual_login_event.is_set():
                    self._manual_login_event.clear()
                    await self._do_login(context)

                if self._manual_sync_event.is_set():
                    self._manual_sync_event.clear()
                    await self._do_collect(context)
                    last_collect = time.time()

                now = time.time()
                collect_due = (now - last_collect) >= COLLECT_INTERVAL_MINUTES * 60
                heartbeat_due = (now - last_heartbeat) >= HEARTBEAT_INTERVAL_MINUTES * 60

                if collect_due:
                    await self._do_collect(context)
                    last_collect = time.time()

                if heartbeat_due:
                    alive = await self._do_heartbeat(context)
                    if not alive:
                        await self._do_login(context)
                    last_heartbeat = time.time()

                next_collect = max(0, COLLECT_INTERVAL_MINUTES * 60 - (time.time() - last_collect))
                next_heartbeat = max(0, HEARTBEAT_INTERVAL_MINUTES * 60 - (time.time() - last_heartbeat))
                self._emit_status({
                    'next_collect': int(next_collect),
                    'next_heartbeat': int(next_heartbeat),
                })

                await asyncio.sleep(5)

            await browser.close()

    async def _check_session(self, context) -> bool:
        page = await context.new_page()
        try:
            await page.goto(SSO_URL, wait_until='domcontentloaded', timeout=20000)
            return 'sto-sso-web' in page.url
        except Exception as e:
            self._emit_log(f'Session 检测失败: {e}')
            return True
        finally:
            await page.close()

    async def _do_login(self, context):
        self._emit_status({'login': '登录中...'})
        self._emit_log('开始登录...')
        page = await context.new_page()
        try:
            await login_via_dingtalk(page)
            await context.storage_state(path=STORAGE_STATE_PATH)
            self._emit_status({'login': '已登录'})
            self._emit_log('登录成功')
        except Exception as e:
            self._emit_status({'login': f'登录失败: {e}'})
            self._emit_log(f'登录失败: {e}')
        finally:
            await page.close()

    async def _do_collect(self, context):
        self._emit_status({'sync': '同步中...'})
        try:
            payloads = await collect_cookies(context)
            await report_cookies(payloads)
            now = datetime.now().strftime('%H:%M:%S')
            self._emit_status({'sync': f'成功 ({now}, {len(payloads)}条)'})
            self._emit_log(f'Cookie 同步成功: {len(payloads)} 条')
        except Exception as e:
            self._emit_status({'sync': f'失败: {e}'})
            self._emit_log(f'Cookie 同步失败: {e}')

    async def _do_heartbeat(self, context) -> bool:
        self._emit_status({'heartbeat': '检测中...'})
        try:
            alive = await heartbeat(context)
            if alive:
                self._emit_status({'heartbeat': '正常'})
                self._emit_log('心跳正常')
            else:
                self._emit_status({'heartbeat': 'Session 过期'})
                self._emit_log('心跳检测: Session 过期，需重新登录')
            return alive
        except Exception as e:
            self._emit_status({'heartbeat': f'异常: {e}'})
            self._emit_log(f'心跳异常: {e}')
            return False

    def trigger_sync(self):
        self._manual_sync_event.set()

    def trigger_login(self):
        self._manual_login_event.set()

    def stop(self):
        self._stop_event.set()

    def _emit_log(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.signals.log_message.emit(f'{ts} {msg}')
        logger.info(msg)

    def _emit_status(self, data: dict):
        self.signals.status_update.emit(data)
