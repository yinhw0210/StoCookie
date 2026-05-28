import asyncio
import json
import socket
import time
from urllib.parse import quote

import httpx
from loguru import logger

from config import REPORT_URLS


def _build_report_url(base_url: str, cookie_str: str, extra_params: dict | None = None) -> str:
    url = f'{base_url}?cookie={quote(cookie_str)}'
    if extra_params:
        for k, v in extra_params.items():
            url += f'&{quote(str(k))}={quote(str(v))}'
    return url


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


async def _resolve_host_ips(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
    ips = []
    seen = set()
    for info in infos:
        ip = info[4][0]
        if ip not in seen:
            seen.add(ip)
            ips.append(ip)
    return ips


async def _get_with_dns_failover(client: httpx.AsyncClient, url: str, emit_log=None, log_category: str = 'report') -> httpx.Response:
    try:
        return await client.get(url)
    except httpx.ConnectError as first_exc:
        parsed = httpx.URL(url)
        host = parsed.host
        if not host:
            raise

        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        default_port = 443 if parsed.scheme == 'https' else 80
        host_header = host if port == default_port else f'{host}:{port}'

        try:
            ips = await _resolve_host_ips(host, port)
        except OSError as dns_exc:
            _emit(
                emit_log,
                f'[上报DNS] host={host} resolve_failed={type(dns_exc).__name__}: {dns_exc}',
                level='warning',
                category=log_category,
            )
            raise first_exc

        if not ips:
            raise first_exc

        _emit(emit_log, f'[上报DNS] host={host} candidates={",".join(ips)}', category=log_category)
        last_exc = first_exc
        for ip in ips:
            started_at = time.perf_counter()
            fallback_url = parsed.copy_with(host=ip)
            request = client.build_request('GET', fallback_url, headers={'Host': host_header})
            if parsed.scheme == 'https':
                request.extensions['sni_hostname'] = host
            try:
                response = await client.send(request)
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                _emit(
                    emit_log,
                    f'[上报DNS尝试] host={host} ip={ip} OK status={response.status_code} elapsed={elapsed_ms}ms',
                    category=log_category,
                )
                return response
            except httpx.ConnectError as exc:
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                last_exc = exc
                _emit(
                    emit_log,
                    f'[上报DNS尝试] host={host} ip={ip} ConnectError elapsed={elapsed_ms}ms error={_error_text(exc)}',
                    level='warning',
                    category=log_category,
                )

        raise last_exc


async def report_cookies(payloads: list[str], emit_log=None, log_category: str = 'report', extra_params: dict | None = None) -> list[dict]:
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
        '[上报配置] method=GET timeout=60s proxy=disabled(trust_env=False) retries=2',
        category=log_category,
    )

    # 仅让 Cookie 上报绕过系统/环境代理，避免代理链路影响写库请求
    transport = httpx.AsyncHTTPTransport(retries=2)
    async with httpx.AsyncClient(timeout=60, trust_env=False, transport=transport) as client:
        for idx, cookie_str in enumerate(payloads, 1):
            entry = {'cookie': cookie_str[:60], 'results': []}
            extra_params_text = f' extra_params={extra_params}' if extra_params else ''
            _emit(
                emit_log,
                f'[上报入参] {idx}/{total} cookie_len={len(cookie_str)} cookie={cookie_str}{extra_params_text}',
                category=log_category,
            )
            for base_url in REPORT_URLS:
                short_name = _short_name(base_url)
                params_text = _request_params(cookie_str)
                started_at = time.perf_counter()
                try:
                    _emit(
                        emit_log,
                        f'[上报请求] {idx}/{total} {short_name} endpoint={base_url} params={params_text}',
                        category=log_category,
                    )
                    url = _build_report_url(base_url, cookie_str, extra_params)
                    resp = await _get_with_dns_failover(client, url, emit_log, log_category)
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
