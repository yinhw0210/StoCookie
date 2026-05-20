from loguru import logger
from playwright.async_api import BrowserContext

from config import HEARTBEAT_URLS, STORAGE_STATE_PATH


async def heartbeat(context: BrowserContext) -> bool:
    for url in HEARTBEAT_URLS:
        page = None
        try:
            page = await context.new_page()
            await page.goto(url, wait_until='domcontentloaded', timeout=15000)
            # 等待可能的重定向
            await page.wait_for_timeout(3000)
            if 'sto-sso-web' in page.url:
                logger.warning(f'心跳检测到 Session 过期 (跳转到登录页): {url}')
                await page.close()
                return False
            await page.close()
        except Exception as e:
            logger.warning(f'心跳访问失败 {url}: {e}')
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    await context.storage_state(path=STORAGE_STATE_PATH)
    logger.debug('心跳保活完成，storageState 已保存')
    return True
