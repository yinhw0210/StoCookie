from typing import Optional

from loguru import logger
from playwright.async_api import BrowserContext

from config import (
    COOKIE_RULES,
    COMBO_RULES,
)


def build_wangdian_kfsd_payload(cookies: list[dict]) -> Optional[str]:
    wd_cookies = [c for c in cookies if 'wangdian.sto.cn' in c.get('domain', '')]
    if not wd_cookies:
        return None
    return 'KFSD=' + ';'.join(f'{c["name"]}={c["value"]}' for c in wd_cookies)


async def collect_cookies(context: BrowserContext) -> list[str]:
    all_cookies = await context.cookies()
    payloads = []
    logger.info(f'开始从浏览器上下文采集 Cookie，总数: {len(all_cookies)}')

    for domain, name, fmt in COOKIE_RULES:
        for c in all_cookies:
            if domain in c.get('domain', '') and c['name'] == name:
                payload = fmt(c['name'], c['value'])
                payloads.append(payload)
                logger.info(f'命中 Cookie 规则: domain={domain}, name={name}, payload={payload[:60]}...')

    for rule in COMBO_RULES:
        target = [
            c for c in all_cookies
            if rule['domain'] in c.get('domain', '') and c['name'] in rule['names']
        ]
        if all(any(c['name'] == n for c in target) for n in rule['names']):
            ordered = []
            for n in rule['names']:
                ordered.append(next(c for c in target if c['name'] == n))
            payload = rule['format'](ordered)
            payloads.append(payload)
            logger.info(
                f'命中组合 Cookie 规则: domain={rule["domain"]}, names={",".join(rule["names"])}, '
                f'payload={payload[:60]}...'
            )

    kfsd_payload = build_wangdian_kfsd_payload(all_cookies)
    if kfsd_payload:
        payloads.append(kfsd_payload)
        logger.info(f'命中 wangdian 全量 Cookie: payload={kfsd_payload[:60]}...')

    logger.info(f'采集到 {len(payloads)} 条 Cookie 数据 (总 Cookie 数: {len(all_cookies)})')
    return payloads
