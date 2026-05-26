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

PERSISTENT_PAGES = [
    'https://page.sto.cn/ux/manipulate-center/index.html#/',
    'https://front.sto.cn/group/customerCenter#/',
    'https://wangdian.sto.cn/page/fin-center/settlement/new-outbound-settlement',
    'https://wangdian.sto.cn/page/external/hq-fin-center/report/policy/transfer/rebate',
    'https://market-cod.sto.cn/cod/topayment/siteOrder/list',
    'https://wangdian.sto.cn/index',
]

FINANCE_FUNDMANAGE_URL = 'https://finance-fundmanage.sto.cn/prepaidment/prepaid/common/getBizType.action?showLevel=1'

WANGDIAN_NAV_SELECTOR = '.navigation-list-item-content'
WANGDIAN_ANNOUNCEMENT_CLOSE_SELECTOR = 'a.next-dialog-close'
WANGDIAN_SEARCH_INPUT_SELECTOR = '.searchMenu-27XOB input[placeholder="支持快捷检索菜单"]'
WANGDIAN_SEARCH_FIRST_RESULT_SELECTOR = 'ul.headerSearchList-1dSEL a.navigation-list-item-content'
WANGDIAN_SEARCH_KEYWORDS = ['结算账户交易明细', '网点账单']

COOKIE_RULES = [
    ('finance-mng.sto.cn', 'SESSION', lambda n, v: f'{n}={v}'),
    ('market-cod.sto.cn', 'cod', lambda n, v: f'{n}={v}'),
    ('finance-fundmanage.sto.cn', 'SESSION', lambda n, v: f'finance={v}'),
    ('.sto.cn', 'spf_sid', lambda n, v: f'{n}={v}'),
    ('.sto.cn', 'stoToken', lambda n, v: f'{n}={v}'),
    ('.sto.cn', 'sid_cfo', lambda n, v: f'{n}={v}'),
    ('.sto.cn', 'WD_SESSION', lambda n, v: f'{n}={v}'),
]

COMBO_RULES = [
    {
        'domain': '.sto.cn',
        'names': ['WD_SESSION', 'TSID'],
        'format': lambda cookies: ';'.join(f'{c["name"]}={c["value"]}' for c in cookies),
    },
    {
        'domain': '.sto.cn',
        'names': ['sid_cfo', 'WD_SESSION', 'TSID'],
        'format': lambda cookies: 'CFO_DOWNLOAD' + ';'.join(f'{c["name"]}={c["value"]}' for c in cookies),
    },
    {
        'domain': '.sto.cn',
        'names': ['stoToken', 'WD_SESSION'],
        'format': lambda cookies: 'WD_STO=' + ';'.join(f'{c["name"]}={c["value"]}' for c in cookies) + ';',
    },
]

REPORT_URLS = [
    # slinghang 暂时不启用，后续需要时再放开。
    'https://slinghang.cn/s/v1/normandy/api/controller/cust/netManager/settingCookie',
    'https://lysto.com.cn/s/v1/normandy/api/controller/cust/netManager/settingCookie',
]

WANGDIAN_MAP_AREA_DETAIL_URL_MARKER = 'wangdian.sto.cn/order/collectMap/query/detail/mapAreaDetail'
WANGDIAN_TRIGGER_INTERVAL_SECONDS = 5 * 60

LOGIN_ENTRY_URL = 'https://wangdian.sto.cn'
SSO_URL = LOGIN_ENTRY_URL
WANGDIAN_INDEX_URL = 'https://wangdian.sto.cn/index'

ROLE_PAGE_SELECTOR = '.accountCorrelation_main_window'
ROLE_ITEM_SELECTOR = '.next-list-item.list_wrap_item'
ROLE_ENTRY_BUTTON_SELECTOR = '.entrybtn'
SAFETY_QUICK_LOGIN_SELECTOR = 'button.ant-btn-primary:has-text("快速登录")'

AUTH_URL_MARKERS = (
    'sto-sso-web',
    'safety-tsportal.sto.cn',
    'login.dingtalk.com',
    '/app_login',
    '/page/expired',
)


def is_auth_url(url: str) -> bool:
    return any(marker in url for marker in AUTH_URL_MARKERS)


def is_logged_in_url(url: str) -> bool:
    return url.startswith(WANGDIAN_INDEX_URL) or url.rstrip('/') == LOGIN_ENTRY_URL

COLLECT_INTERVAL_MINUTES = 60
HEARTBEAT_INTERVAL_MINUTES = 60

# PDD 站点配置
PDD_LOGIN_URL = 'https://56-partner.pinduoduo.com/auth/login'
PDD_TARGET_URL = 'https://56-partner.pinduoduo.com/delivery-workbench/order'
PDD_COOKIE_DOMAIN = '56-partner-api.pinduoduo.com'
PDD_COOKIE_NAME = 'SUB_PASS_ID'
PDD_STORAGE_PATH = os.path.join(STORAGE_DIR, 'pdd_state.json')
