from typing import Optional

from loguru import logger
from playwright.async_api import BrowserContext

from config import (
    COOKIE_RULES,
    COMBO_RULES,
    COOKIE_SEED_URLS,
    ROLE_ITEM_SELECTOR,
    ROLE_PAGE_SELECTOR,
    is_auth_url,
)


def build_wangdian_kfsd_payload(cookies: list[dict]) -> Optional[str]:
    wd_cookies = [c for c in cookies if 'wangdian.sto.cn' in c.get('domain', '')]
    if not wd_cookies:
        return None
    return 'KFSD=' + ';'.join(f'{c["name"]}={c["value"]}' for c in wd_cookies)


async def visit_cookie_seed_pages(context: BrowserContext) -> list[dict]:
    """访问各业务页面，确保浏览器产生对应域名的 Cookie。"""
    results = []
    page = await context.new_page()
    try:
        for url in COOKIE_SEED_URLS:
            result = {'url': url, 'ok': False, 'final_url': '', 'reason': None}
            try:
                logger.info(f'开始访问种子页面: {url}')
                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                result['final_url'] = page.url
                if is_auth_url(page.url):
                    result['reason'] = f'进入认证页: {page.url}'
                    logger.warning(f'种子页面跳过，进入认证页: {url} -> {page.url}')
                    results.append(result)
                    continue
                role_page_visible = False
                try:
                    role_page_visible = await page.locator(ROLE_PAGE_SELECTOR).first.is_visible(timeout=1000)
                except Exception:
                    pass
                role_item_visible = False
                try:
                    role_item_visible = await page.locator(ROLE_ITEM_SELECTOR).first.is_visible(timeout=1000)
                except Exception:
                    pass
                if role_page_visible or role_item_visible:
                    result['reason'] = '进入角色选择页'
                    logger.warning(f'种子页面跳过，进入角色选择页: {url} -> {page.url}')
                    results.append(result)
                    continue
                await page.wait_for_timeout(2000)
                result['ok'] = True
                logger.info(f'种子页面访问成功: {url} -> {page.url}')
            except Exception as e:
                result['reason'] = str(e)
                logger.warning(f'种子页面访问失败: {url} -> {e}')
            results.append(result)
    finally:
        try:
            await page.close()
        except Exception:
            pass
    return results


async def collect_cookies(context: BrowserContext) -> list[str]:
    all_cookies = await context.cookies()
    payloads = []
    logger.info(f'开始从浏览器上下文采集 Cookie，总数: {len(all_cookies)}')

    # 单条 Cookie 规则
    for domain, name, fmt in COOKIE_RULES:
        for c in all_cookies:
            if domain in c.get('domain', '') and c['name'] == name:
                payload = fmt(c['name'], c['value'])
                payloads.append(payload)
                logger.info(f'命中 Cookie 规则: domain={domain}, name={name}, payload={payload[:60]}...')

    # 组合 Cookie 规则
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

    # wangdian.sto.cn 全量 Cookie (KFSD)
    kfsd_payload = build_wangdian_kfsd_payload(all_cookies)
    if kfsd_payload:
        payloads.append(kfsd_payload)
        logger.info(f'命中 wangdian 全量 Cookie: payload={kfsd_payload[:60]}...')

    logger.info(f'采集到 {len(payloads)} 条 Cookie 数据 (总 Cookie 数: {len(all_cookies)})')
    return payloads
