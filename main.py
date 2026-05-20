import asyncio
import os
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from playwright.async_api import async_playwright

from config import (
    COLLECT_INTERVAL_MINUTES,
    HEARTBEAT_INTERVAL_MINUTES,
    SSO_URL,
    STORAGE_STATE_PATH,
)
from cookie_collector import collect_cookies
from cookie_reporter import report_cookies
from heartbeat import heartbeat
from login import login_via_dingtalk

logger.remove()
logger.add(sys.stderr, level='INFO')
logger.add('logs/cookie-automation.log', rotation='10 MB', retention='7 days', level='DEBUG')


async def do_login(context):
    page = await context.new_page()
    try:
        await login_via_dingtalk(page)
        await context.storage_state(path=STORAGE_STATE_PATH)
    finally:
        await page.close()


async def main():
    os.makedirs('storage', exist_ok=True)
    os.makedirs('logs', exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        if os.path.exists(STORAGE_STATE_PATH):
            logger.info('恢复已有 Session...')
            context = await browser.new_context(storage_state=STORAGE_STATE_PATH)
        else:
            logger.info('无已有 Session，创建新 context')
            context = await browser.new_context()

        page = await context.new_page()
        await page.goto(SSO_URL, wait_until='domcontentloaded', timeout=20000)
        need_login = 'sto-sso-web' in page.url
        await page.close()

        if need_login:
            logger.info('Session 无效，执行登录...')
            await do_login(context)
        else:
            logger.info('Session 有效，跳过登录')

        scheduler = AsyncIOScheduler()

        @scheduler.scheduled_job('interval', minutes=COLLECT_INTERVAL_MINUTES, id='collect')
        async def job_collect():
            try:
                payloads = await collect_cookies(context)
                await report_cookies(payloads)
            except Exception as e:
                logger.error(f'Cookie 采集上报异常: {e}')

        @scheduler.scheduled_job('interval', minutes=HEARTBEAT_INTERVAL_MINUTES, id='heartbeat')
        async def job_heartbeat():
            try:
                alive = await heartbeat(context)
                if not alive:
                    logger.warning('Session 过期，自动重新登录...')
                    await do_login(context)
            except Exception as e:
                logger.error(f'心跳/重登录异常: {e}')

        scheduler.start()
        logger.info(
            f'调度器已启动: 采集间隔={COLLECT_INTERVAL_MINUTES}min, 心跳间隔={HEARTBEAT_INTERVAL_MINUTES}min'
        )

        # 立即执行一次采集
        await job_collect()

        try:
            while True:
                await asyncio.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            logger.info('收到退出信号，正在关闭...')
            scheduler.shutdown()
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
