import os
import sys

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STORAGE_DIR = os.path.join(BASE_DIR, 'storage')
LOG_DIR = os.path.join(BASE_DIR, 'logs')
BROWSERS_DIR = os.path.join(BASE_DIR, 'browsers')
SETTINGS_PATH = os.path.join(BASE_DIR, 'settings.json')

STORAGE_STATE_PATH = os.path.join(STORAGE_DIR, 'state.json')

HEARTBEAT_URLS = [
    'https://page.sto.cn/ux/manipulate-center/index',
    'https://front.sto.cn/group/customerCenter#/',
    'https://wangdian.sto.cn/page/fin-center/settlement/new-outbound-settlement',
    'https://wangdian.sto.cn/page/external/hq-fin-center/report/policy/transfer/rebate',
    'https://market-cod.sto.cn/cod/topayment/siteOrder/list',
    'https://finance-fundmanage.sto.cn/prepaidment/prepaid/common/getBizType.action?showLevel=1',
]

# 采集前需要访问的页面（确保浏览器产生对应域名的 Cookie）
COOKIE_SEED_URLS = [
    'https://finance-mng.sto.cn/',
    'https://market-cod.sto.cn/cod/topayment/siteOrder/list',
    'https://finance-fundmanage.sto.cn/prepaidment/prepaid/common/getBizType.action?showLevel=1',
    'https://wutonggateway.sto.cn/',
    'https://wangdian.sto.cn/page/fin-center/settlement/new-outbound-settlement',
]

COOKIE_RULES = [
    ('finance-mng.sto.cn', 'SESSION', lambda n, v: f'{n}={v}'),
    ('market-cod.sto.cn', 'cod', lambda n, v: f'{n}={v}'),
    ('finance-fundmanage.sto.cn', 'SESSION', lambda n, v: f'finance={v}'),
    ('wutonggateway.sto.cn', 'spf_sid', lambda n, v: f'{n}={v}'),
    ('wutonggateway.sto.cn', 'stoToken', lambda n, v: f'{n}={v}'),
    ('wutonggateway.sto.cn', 'sid_cfo', lambda n, v: f'{n}={v}'),
    ('wutonggateway.sto.cn', 'WD_SESSION', lambda n, v: f'{n}={v}'),
]

COMBO_RULES = [
    {
        'domain': 'wutonggateway.sto.cn',
        'names': ['WD_SESSION', 'TSID'],
        'format': lambda cookies: ';'.join(f'{c["name"]}={c["value"]}' for c in cookies),
    },
    {
        'domain': 'wutonggateway.sto.cn',
        'names': ['sid_cfo', 'WD_SESSION', 'TSID'],
        'format': lambda cookies: 'CFO_DOWNLOAD' + ';'.join(f'{c["name"]}={c["value"]}' for c in cookies),
    },
]

REPORT_URLS = [
    'https://slinghang.cn/s/v1/normandy/api/controller/cust/netManager/settingCookie',
    'https://lysto.com.cn/s/v1/normandy/api/controller/cust/netManager/settingCookie',
]

SSO_URL = 'https://page.sto.cn/sto-base-service/sto-sso-web/#/main?autoLogin=true&systemCode=SITE_KEEPER&returnUrl=/index'

COLLECT_INTERVAL_MINUTES = 360
HEARTBEAT_INTERVAL_MINUTES = 20
