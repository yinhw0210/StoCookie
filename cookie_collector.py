from loguru import logger
from playwright.async_api import BrowserContext

from config import COOKIE_RULES, COMBO_RULES


async def collect_cookies(context: BrowserContext) -> list[str]:
    all_cookies = await context.cookies()
    payloads = []

    for domain, name, fmt in COOKIE_RULES:
        for c in all_cookies:
            if domain in c.get('domain', '') and c['name'] == name:
                payloads.append(fmt(c['name'], c['value']))

    for rule in COMBO_RULES:
        target = [
            c for c in all_cookies
            if rule['domain'] in c.get('domain', '') and c['name'] in rule['names']
        ]
        if all(any(c['name'] == n for c in target) for n in rule['names']):
            payloads.append(rule['format'](target))

    wd_cookies = [c for c in all_cookies if 'wangdian.sto.cn' in c.get('domain', '')]
    if wd_cookies:
        payloads.append('KFSD=' + ';'.join(f'{c["name"]}={c["value"]}' for c in wd_cookies))

    logger.debug(f'采集到 {len(payloads)} 条 Cookie 数据')
    return payloads
