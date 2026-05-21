import time
from urllib.parse import quote

import httpx
from loguru import logger

from config import REPORT_URLS


async def report_cookies(payloads: list[str]) -> list[dict]:
    """
    上报 Cookie，返回逐条详细结果。
    每条: {'cookie': 'SESSION=xxx...', 'results': [{'url': 'lysto', 'ok': True, 'error': None}, ...]}
    """
    if not payloads:
        return []

    reports = []

    # 仅让 Cookie 上报绕过系统/环境代理，避免代理链路影响写库请求
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        for cookie_str in payloads:
            entry = {'cookie': cookie_str[:60], 'results': []}
            for base_url in REPORT_URLS:
                url = f'{base_url}?cookie={quote(cookie_str)}'
                short_name = base_url.split('//')[1].split('.')[0]
                started_at = time.perf_counter()
                try:
                    logger.debug(f'上报请求开始: {short_name} ← {cookie_str[:40]}...')
                    resp = await client.get(url)
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    if resp.status_code == 200:
                        body = resp.text
                        # 检查响应体是否包含错误信息
                        if '"code":0' in body or '"success":true' in body.lower() or len(body) < 5:
                            entry['results'].append({'url': short_name, 'ok': True, 'error': None})
                            logger.debug(f'上报成功: {short_name} ← {cookie_str[:40]}... ({elapsed_ms}ms)')
                        else:
                            entry['results'].append({'url': short_name, 'ok': False, 'error': body[:100]})
                            logger.warning(f'上报返回异常: {short_name} ({elapsed_ms}ms) → {body[:100]}')
                    else:
                        entry['results'].append({'url': short_name, 'ok': False, 'error': f'HTTP {resp.status_code}'})
                        logger.warning(f'上报异常 HTTP {resp.status_code}: {short_name} ({elapsed_ms}ms)')
                except Exception as e:
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    err_text = f'{type(e).__name__}: {e!r}'
                    entry['results'].append({'url': short_name, 'ok': False, 'error': err_text[:120]})
                    logger.exception(f'上报失败: {short_name} ({elapsed_ms}ms) → {err_text}')
            reports.append(entry)

    return reports
