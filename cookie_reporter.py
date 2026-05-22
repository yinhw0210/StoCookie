import time
from urllib.parse import quote

import httpx
from loguru import logger

from config import REPORT_URLS


def _build_report_url(base_url: str, cookie_str: str) -> str:
    return f'{base_url}?cookie={quote(cookie_str)}'


async def report_cookies(payloads: list[str]) -> list[dict]:
    """
    上报 Cookie，返回逐条详细结果。
    每条: {'cookie': 'SESSION=xxx...', 'results': [{'url': 'lysto', 'ok': True, 'error': None}, ...]}
    """
    if not payloads:
        logger.info('[上报] 无 payload，跳过')
        return []

    reports = []
    total = len(payloads)
    logger.info(f'[上报] 开始，共 {total} 条 payload，目标 {len(REPORT_URLS)} 个接口')

    # 仅让 Cookie 上报绕过系统/环境代理，避免代理链路影响写库请求
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        for idx, cookie_str in enumerate(payloads, 1):
            entry = {'cookie': cookie_str[:60], 'results': []}
            logger.info(
                f'[上报准备] {idx}/{total} payload明文({len(cookie_str)}字符): {cookie_str}'
            )
            for base_url in REPORT_URLS:
                url = _build_report_url(base_url, cookie_str)
                short_name = base_url.split('//')[1].split('.')[0]
                started_at = time.perf_counter()
                try:
                    logger.info(f'[上报请求] {idx}/{total} {short_name} GET {url}')
                    resp = await client.get(url)
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    body = resp.text
                    if resp.status_code == 200:
                        # 检查响应体是否包含错误信息
                        if '"code":0' in body or '"success":true' in body.lower() or len(body) < 5:
                            entry['results'].append({'url': short_name, 'ok': True, 'error': None})
                            logger.info(
                                f'[上报响应] {idx}/{total} {short_name} OK HTTP 200 '
                                f'({elapsed_ms}ms) body={body}'
                            )
                        else:
                            entry['results'].append({'url': short_name, 'ok': False, 'error': body[:100]})
                            logger.warning(
                                f'[上报响应] {idx}/{total} {short_name} FAIL HTTP 200 业务异常 '
                                f'({elapsed_ms}ms) body={body}'
                            )
                    else:
                        entry['results'].append({'url': short_name, 'ok': False, 'error': f'HTTP {resp.status_code}'})
                        logger.warning(
                            f'[上报响应] {idx}/{total} {short_name} FAIL HTTP {resp.status_code} '
                            f'({elapsed_ms}ms) body={body[:500]}'
                        )
                except Exception as e:
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    err_text = f'{type(e).__name__}: {e!r}'
                    entry['results'].append({'url': short_name, 'ok': False, 'error': err_text[:120]})
                    logger.exception(
                        f'[上报响应] {idx}/{total} {short_name} ERROR ({elapsed_ms}ms) '
                        f'url={url} err={err_text}'
                    )
            reports.append(entry)

    ok_count = sum(1 for entry in reports for r in entry['results'] if r['ok'])
    fail_count = sum(1 for entry in reports for r in entry['results'] if not r['ok'])
    logger.info(f'[上报] 结束，请求成功 {ok_count} / 失败 {fail_count}')
    return reports
