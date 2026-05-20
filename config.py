HEARTBEAT_URLS = [
    'https://page.sto.cn/ux/manipulate-center/index',
    'https://front.sto.cn/group/customerCenter#/',
    'https://wangdian.sto.cn/page/fin-center/settlement/new-outbound-settlement',
    'https://wangdian.sto.cn/page/external/hq-fin-center/report/policy/transfer/rebate',
    'https://market-cod.sto.cn/cod/topayment/siteOrder/list',
    'https://finance-fundmanage.sto.cn/prepaidment/prepaid/common/getBizType.action?showLevel=1',
]

COOKIE_RULES = [
    ('finance-mng.sto.cn', 'SESSION', lambda n, v: f'{n}={v}'),
    ('market-cod.sto.cn', 'cod', lambda n, v: f'{n}={v}'),
    ('finance-fundmanage.sto.cn', 'SESSION', lambda n, v: f'finance={v}'),
    ('wutonggateway.sto.cn', 'spf_sid', lambda n, v: f'{n}={v}'),
    ('wutonggateway.sto.cn', 'stoToken', lambda n, v: f'{n}={v}'),
    ('wutonggateway.sto.cn', 'sid_cfo', lambda n, v: f'{n}={v}'),
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
        'format': lambda cookies: 'CFO_DOWNLOAD' + ''.join(f'{c["name"]}={c["value"]}' for c in cookies),
    },
]

REPORT_URLS = [
    'https://slinghang.cn/s/v1/normandy/api/controller/cust/netManager/settingCookie',
    'https://lysto.com.cn/s/v1/normandy/api/controller/cust/netManager/settingCookie',
]

SSO_URL = 'https://page.sto.cn/sto-base-service/sto-sso-web/#/main?autoLogin=true&systemCode=SITE_KEEPER&returnUrl=/index'

STORAGE_STATE_PATH = 'storage/state.json'

COLLECT_INTERVAL_MINUTES = 1
HEARTBEAT_INTERVAL_MINUTES = 3
