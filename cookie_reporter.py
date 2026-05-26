import json
import time
from urllib.parse import quote

import httpx
from loguru import logger

from config import REPORT_URLS


def _build_report_url(base_url: str, cookie_str: str) -> str:
    return f'{base_url}?cookie={quote(cookie_str)}'


def _short_name(base_url: str) -> str:
    return base_url.split('//')[1].split('.')[0]


def _clip(text: str, limit: int = 1000) -> str:
    if len(text) <= limit:
        return text
    return f'{text[:limit]}...<truncated {len(text) - limit} chars>'


def _error_text(exc: Exception) -> str:
    parts = [f'{type(exc).__name__}: {exc}']
    cause = exc.__cause__ or exc.__context__
    if cause:
        parts.append(f'cause={type(cause).__name__}: {cause}')
    return ' | '.join(parts)


def _request_params(cookie_str: str) -> str:
    return json.dumps({'cookie': cookie_str}, ensure_ascii=False)


def _emit(emit_log, message: str, level: str = 'info', category: str = 'report'):
    if emit_log:
        emit_log(message, category)
        return

    if level == 'warning':
        logger.warning(message)
    else:
        logger.info(message)


async def report_cookies(payloads: list[str], emit_log=None, log_category: str = 'report') -> list[dict]:
    """
    上报 Cookie，返回逐条详细结果。
    每条: {'cookie': 'SESSION=xxx...', 'results': [{'url': 'lysto', 'ok': True, 'error': None}, ...]}
    """
    if not payloads:
        _emit(emit_log, '[上报] 无 payload，跳过', category=log_category)
        return []

    reports = []
    total = len(payloads)
    targets = ', '.join(_short_name(url) for url in REPORT_URLS)
    _emit(
        emit_log,
        f'[上报] 开始，共 {total} 条 payload，目标 {len(REPORT_URLS)} 个接口: {targets}',
        category=log_category,
    )
    _emit(
        emit_log,
        '[上报配置] method=GET timeout=10s proxy=disabled(trust_env=False)',
        category=log_category,
    )

    # 仅让 Cookie 上报绕过系统/环境代理，避免代理链路影响写库请求
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        for idx, cookie_str in enumerate(payloads, 1):
            entry = {'cookie': cookie_str[:60], 'results': []}
            _emit(
                emit_log,
                f'[上报入参] {idx}/{total} cookie_len={len(cookie_str)} cookie={cookie_str}',
                category=log_category,
            )
            for base_url in REPORT_URLS:
                url = _build_report_url(base_url, cookie_str)
                short_name = _short_name(base_url)
                params_text = _request_params(cookie_str)
                started_at = time.perf_counter()
                try:
                    _emit(
                        emit_log,
                        f'[上报请求] {idx}/{total} {short_name} endpoint={base_url} params={params_text}',
                        category=log_category,
                    )
                    resp = await client.get(url)
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    body = _clip(resp.text)
                    content_type = resp.headers.get('content-type', '')
                    if resp.status_code == 200:
                        # 检查响应体是否包含错误信息
                        if '"code":0' in resp.text or '"success":true' in resp.text.lower() or len(resp.text) < 5:
                            entry['results'].append({'url': short_name, 'ok': True, 'error': None})
                            _emit(
                                emit_log,
                                f'[上报出参] {idx}/{total} {short_name} OK status=200 elapsed={elapsed_ms}ms '
                                f'content_type={content_type} body={body}',
                                category=log_category,
                            )
                        else:
                            entry['results'].append({'url': short_name, 'ok': False, 'error': resp.text[:100]})
                            _emit(
                                emit_log,
                                f'[上报出参] {idx}/{total} {short_name} FAIL status=200 elapsed={elapsed_ms}ms '
                                f'content_type={content_type} body={body}',
                                level='warning',
                                category=log_category,
                            )
                    else:
                        entry['results'].append({'url': short_name, 'ok': False, 'error': f'HTTP {resp.status_code}'})
                        _emit(
                            emit_log,
                            f'[上报出参] {idx}/{total} {short_name} FAIL status={resp.status_code} elapsed={elapsed_ms}ms '
                            f'content_type={content_type} body={body}',
                            level='warning',
                            category=log_category,
                        )
                except Exception as e:
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    err_text = _error_text(e)
                    entry['results'].append({'url': short_name, 'ok': False, 'error': err_text[:120]})
                    _emit(
                        emit_log,
                        f'[上报异常] {idx}/{total} {short_name} elapsed={elapsed_ms}ms endpoint={base_url} '
                        f'params={params_text} error={err_text}',
                        level='warning',
                        category=log_category,
                    )
            reports.append(entry)

    ok_count = sum(1 for entry in reports for r in entry['results'] if r['ok'])
    fail_count = sum(1 for entry in reports for r in entry['results'] if not r['ok'])
    _emit(emit_log, f'[上报] 结束，请求成功 {ok_count} / 失败 {fail_count}', category=log_category)
    return reports
