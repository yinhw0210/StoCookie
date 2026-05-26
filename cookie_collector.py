from typing import Optional

from loguru import logger
from playwright.async_api import BrowserContext

from config import (
    COOKIE_RULES,
    COMBO_RULES,
)


def _domain_match(cookie_domain: str, rule_domain: str) -> bool:
    """
    模拟浏览器 cookie domain 匹配逻辑：
    - rule_domain 以 '.' 开头（如 '.sto.cn'）：cookie_domain 精确等于它，
      或者 cookie_domain 以该后缀结尾（如 'wutonggateway.sto.cn' 匹配 '.sto.cn'）
    - 否则：cookie_domain 包含 rule_domain 即可
    """
    if rule_domain.startswith('.'):
        return cookie_domain == rule_domain or cookie_domain.endswith(rule_domain)
    return rule_domain in cookie_domain

# STO 上报的完整类型列表（用于 GUI 展示逐条状态）
EXPECTED_REPORT_ITEMS = [
    {'label': 'SESSION (finance-mng)', 'rule_domain': 'finance-mng.sto.cn', 'rule_name': 'SESSION'},
    {'label': 'cod (market-cod)', 'rule_domain': 'market-cod.sto.cn', 'rule_name': 'cod'},
    {'label': 'finance (finance-fundmanage)', 'rule_domain': 'finance-fundmanage.sto.cn', 'rule_name': 'SESSION'},
    {'label': 'spf_sid (wutonggateway)', 'rule_domain': 'wutonggateway.sto.cn', 'rule_name': 'spf_sid'},
    {'label': 'stoToken (wutonggateway)', 'rule_domain': 'wutonggateway.sto.cn', 'rule_name': 'stoToken'},
    {'label': 'sid_cfo (wutonggateway)', 'rule_domain': 'wutonggateway.sto.cn', 'rule_name': 'sid_cfo'},
    {'label': 'WD_SESSION (wutonggateway)', 'rule_domain': 'wutonggateway.sto.cn', 'rule_name': 'WD_SESSION'},
    {'label': 'WD_SESSION+TSID 组合', 'combo': True, 'names': ['WD_SESSION', 'TSID']},
    {'label': 'CFO_DOWNLOAD 组合', 'combo': True, 'names': ['sid_cfo', 'WD_SESSION', 'TSID']},
    {'label': 'KFSD (wangdian全量)', 'kfsd': True},
]


def build_wangdian_kfsd_payload(cookies: list[dict]) -> Optional[str]:
    wd_cookies = [c for c in cookies if 'wangdian.sto.cn' in c.get('domain', '')]
    if not wd_cookies:
        return None
    return 'KFSD=' + ';'.join(f'{c["name"]}={c["value"]}' for c in wd_cookies)


async def collect_cookies(context: BrowserContext) -> list[str]:
    all_cookies = await context.cookies()
    payloads = []

    # 按域名分组打印所有 cookie 的 domain 和 name，便于排查
    domains_summary = {}
    for c in all_cookies:
        d = c.get('domain', '')
        if d not in domains_summary:
            domains_summary[d] = []
        domains_summary[d].append(c['name'])

    logger.info(f'Context 中共有 {len(all_cookies)} 个 Cookie，涉及 {len(domains_summary)} 个域名')
    for d, names in sorted(domains_summary.items()):
        logger.info(f'  域名 {d}: {", ".join(names)}')

    # 单条规则匹配
    for domain, name, fmt in COOKIE_RULES:
        matched = [c for c in all_cookies if _domain_match(c.get('domain', ''), domain) and c['name'] == name]
        if matched:
            c = matched[0]
            payload = fmt(c['name'], c['value'])
            payloads.append(payload)
            logger.info(f'[采集] ✓ 命中规则: {name}@{domain} → payload明文({len(payload)}字符): {payload}')
        else:
            domain_cookies = [c for c in all_cookies if _domain_match(c.get('domain', ''), domain)]
            if domain_cookies:
                actual_names = [c['name'] for c in domain_cookies]
                logger.warning(f'✗ 未命中规则: {name}@{domain}，该域名下实际有: {", ".join(actual_names)}')
            else:
                logger.warning(f'✗ 未命中规则: {name}@{domain}，Context 中无此域名的 Cookie')

    # 组合规则匹配
    for rule in COMBO_RULES:
        target = [
            c for c in all_cookies
            if _domain_match(c.get('domain', ''), rule['domain']) and c['name'] in rule['names']
        ]
        found_names = [c['name'] for c in target]
        missing_names = [n for n in rule['names'] if n not in found_names]
        if not missing_names:
            ordered = []
            for n in rule['names']:
                ordered.append(next(c for c in target if c['name'] == n))
            payload = rule['format'](ordered)
            payloads.append(payload)
            logger.info(
                f'[采集] ✓ 命中组合规则: {",".join(rule["names"])}@{rule["domain"]} '
                f'→ payload明文({len(payload)}字符): {payload}'
            )
        else:
            logger.warning(f'✗ 未命中组合规则: {",".join(rule["names"])}@{rule["domain"]}，缺少: {",".join(missing_names)}')

    # KFSD 全量
    kfsd_payload = build_wangdian_kfsd_payload(all_cookies)
    if kfsd_payload:
        payloads.append(kfsd_payload)
        logger.info(
            f'[采集] ✓ 命中 KFSD: wangdian 全量 Cookie '
            f'payload明文({len(kfsd_payload)}字符): {kfsd_payload}'
        )
    else:
        logger.warning('✗ 未命中 KFSD: Context 中无 wangdian.sto.cn 的 Cookie')

    logger.info(f'[采集] 结束，共 {len(payloads)} 条 payload 待上报')
    for i, p in enumerate(payloads, 1):
        logger.info(f'[采集] 待上报清单 {i}/{len(payloads)}: {p}')
    return payloads
