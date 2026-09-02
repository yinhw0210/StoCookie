from __future__ import annotations

import asyncio
import base64
import json
import os

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page

from config import (
    KUNLUN_ORG,
    KUNLUN_REPORT_KEY,
    KUNLUN_SCAN_PANEL_SELECTOR,
    KUNLUN_SEARCH_BTN_SELECTOR,
    KUNLUN_SEARCH_INPUT_SELECTOR,
    KUNLUN_SEARCH_KEYWORD,
    KUNLUN_SEARCH_RESULT_SELECTOR,
    KUNLUN_SESSION_STORAGE_KEY,
    KUNLUN_STORAGE_PATH,
    KUNLUN_URL,
    is_auth_url,
)
from login import login_via_dingtalk


def _is_kunlun_host_url(url: str) -> bool:
    """是否已回到昆仑域名（含 SSO 回跳 ?code=...）。

    钉钉登录后常停在 https://kunlun.sto.cn/?code=xxx&returnUrl=/ ，
    SPA 已登录但 URL 仍带 code；此前把带 code 一律判失败，导致
    「页面已登录却报登录未完成、不走搜索采 cookie」。
    真正是否可用改由业务壳（搜索按钮）判定。
    """
    u = url or ''
    return 'kunlun.sto.cn' in u and not is_auth_url(u)


def _is_kunlun_success_url(url: str) -> bool:
    return _is_kunlun_host_url(url)


def _is_scan_query_ready_url(url: str) -> bool:
    """扫描查询打开后的合法落地页（iframe 面板路由或九天 page-info）。"""
    u = url or ''
    if 'kunlun.sto.cn' not in u:
        return False
    if '/device/scanQuery' in u or 'scanQuery' in u:
        return True
    if '/jiutian/page-info/' in u and (
        '%E6%89%AB%E6%8F%8F%E6%9F%A5%E8%AF%A2' in u  # 扫描查询
        or 'title=%E6%89%AB%E6%8F%8F' in u
        or '扫描查询' in u
    ):
        return True
    return False


def _accounts_match(expected: str, actual: str) -> bool:
    """网点管家 userName 与昆仑展示名/token 名模糊对齐。"""
    a = (expected or '').strip()
    b = (actual or '').strip()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _decode_jwt_payload(token: str) -> dict:
    try:
        parts = (token or '').split('.')
        if len(parts) < 2:
            return {}
        payload = parts[1]
        payload += '=' * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(payload.encode('utf-8'))
        return json.loads(raw.decode('utf-8'))
    except Exception:
        return {}


def _name_from_sto_token(token: str) -> str:
    """从 __stoToken JWT 解析真实姓名 / 用户名。"""
    data = _decode_jwt_payload(token)
    userinfo_raw = data.get('USERINFO') or data.get('USER_INFO') or ''
    info = {}
    if isinstance(userinfo_raw, str) and userinfo_raw:
        try:
            info = json.loads(userinfo_raw)
        except Exception:
            info = {}
    elif isinstance(userinfo_raw, dict):
        info = userinfo_raw
    return (
        (info.get('realName') or info.get('nickName') or info.get('userName') or '')
        if isinstance(info, dict)
        else ''
    )


class KunlunSiteDriver:
    name = '昆仑'

    def __init__(self, emit_log=None):
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._browser: Browser | None = None
        self._emit_log = emit_log or (lambda msg, cat: logger.info(msg))

    async def create_context(self, browser: Browser, *, restore: bool = True) -> BrowserContext:
        self._browser = browser
        context_opts = {'no_viewport': True}
        if restore and os.path.exists(KUNLUN_STORAGE_PATH):
            context_opts['storage_state'] = KUNLUN_STORAGE_PATH
            self._context = await browser.new_context(**context_opts)
            self._emit_log(f'昆仑: 恢复已有 Session → {KUNLUN_STORAGE_PATH}', 'kunlun')
        else:
            if not restore and os.path.exists(KUNLUN_STORAGE_PATH):
                # 明确要求不恢复时，落盘一并删掉，避免后续路径又读回来
                try:
                    os.remove(KUNLUN_STORAGE_PATH)
                    self._emit_log(f'昆仑: create_context(restore=False)，已删除 {KUNLUN_STORAGE_PATH}', 'kunlun')
                except Exception as e:
                    self._emit_log(f'昆仑: 删除 storage 失败: {e}', 'kunlun')
            self._context = await browser.new_context(**context_opts)
            self._emit_log('昆仑: 创建新 Context（不恢复 Session）', 'kunlun')
        return self._context

    async def invalidate_session(self, reason: str = '') -> None:
        """清空昆仑独立 context 的 cookie / 落盘状态，强制下次走钉钉重登。

        关键：只要 storage_state 还在，goto 昆仑会直接进旧号，根本不会走钉钉选新号。
        用户手动删 storage 才能换号 —— 本方法就是自动化这一步。
        """
        reason_text = f' ({reason})' if reason else ''
        self._emit_log(f'昆仑: 失效 Session{reason_text}，清理 cookie 与落盘状态', 'kunlun')
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
        except Exception:
            pass
        self._page = None

        try:
            if self._context:
                await self._context.clear_cookies()
        except Exception as e:
            self._emit_log(f'昆仑: clear_cookies 失败: {e}', 'kunlun')

        try:
            if os.path.exists(KUNLUN_STORAGE_PATH):
                os.remove(KUNLUN_STORAGE_PATH)
                self._emit_log(f'昆仑: 已删除 {KUNLUN_STORAGE_PATH}', 'kunlun')
            else:
                self._emit_log(f'昆仑: 落盘不存在，无需删除: {KUNLUN_STORAGE_PATH}', 'kunlun')
        except Exception as e:
            self._emit_log(f'昆仑: 删除 storage 失败: {e}', 'kunlun')

        # 用干净 context 替换，避免旧 localStorage/sessionStorage 残留
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        self._context = None
        if self._browser:
            self._context = await self._browser.new_context(no_viewport=True)
            self._emit_log('昆仑: 已重建干净 Context', 'kunlun')

    async def ensure_page(self):
        """确保常驻页面存在；不存在则新建并导航到昆仑扫描查询入口。"""
        if self._page and not self._page.is_closed():
            return
        if not self._context:
            raise RuntimeError('昆仑 Context 未创建')
        self._page = await self._context.new_page()
        self._emit_log(f'昆仑: 新开常驻页面，导航到 {KUNLUN_URL}', 'kunlun')
        await self._page.goto(KUNLUN_URL, wait_until='domcontentloaded', timeout=30000)
        await self._page.wait_for_timeout(3000)

    async def _shell_ready(self) -> bool:
        """业务壳是否可用：搜索按钮可见。"""
        try:
            btn = self._page.locator(KUNLUN_SEARCH_BTN_SELECTOR).first
            return await btn.is_visible(timeout=3000)
        except Exception:
            return False

    async def check_session(self) -> bool:
        """reload 检测 session；认证页 / 无业务壳 → 过期。带 ?code= 但壳已就绪仍算有效。"""
        try:
            await self.ensure_page()
            self._emit_log('昆仑: 复用常驻页面检测 Session (reload)', 'kunlun')
            await self._page.reload(wait_until='domcontentloaded', timeout=30000)
            await self._page.wait_for_timeout(3000)
            url = self._page.url
            if not _is_kunlun_host_url(url):
                self._emit_log(f'昆仑: Session 过期或未进入昆仑: {url}', 'kunlun')
                return False
            if not await self._shell_ready():
                # 停在 ?code= 且壳未出：尝试进目标页再判一次
                if '?code=' in url or '&code=' in url:
                    self._emit_log(f'昆仑: 停在 SSO code 回跳且壳未就绪，goto 目标页重试: {url}', 'kunlun')
                    await self._page.goto(KUNLUN_URL, wait_until='domcontentloaded', timeout=30000)
                    await self._page.wait_for_timeout(3000)
                    if await self._shell_ready():
                        self._emit_log(f'昆仑: Session 有效（code 回跳后壳已就绪）: {self._page.url}', 'kunlun')
                        return True
                self._emit_log(f'昆仑: Session URL 在昆仑但业务壳未就绪: {self._page.url}', 'kunlun')
                return False
            self._emit_log(f'昆仑: Session 有效，当前 URL: {url}', 'kunlun')
            return True
        except Exception as e:
            self._emit_log(f'昆仑: Session 检测异常: {e}', 'kunlun')
            return False

    async def read_displayed_account(self) -> str:
        """读取昆仑当前登录名：优先 JWT __stoToken，其次头像 text。"""
        try:
            await self.ensure_page()
            # 1) token 最准（与上报同源）
            token = await self._read_sto_token()
            name = _name_from_sto_token(token)
            if name:
                self._emit_log(f'昆仑: 从 __stoToken 解析到账号名: {name}', 'kunlun')
                return name

            # 2) 头像兜底
            name = await self._page.evaluate(
                """() => {
                    const sels = [
                        '.shell-ui-user-avatar',
                        '.sto-shell-user-avatar',
                        '.user-info [class*="avatar"]',
                        '[class*="user-avatar"]',
                    ];
                    for (const s of sels) {
                        const el = document.querySelector(s);
                        if (!el) continue;
                        const t = (el.getAttribute('text') || el.textContent || '').trim();
                        if (t) return t;
                    }
                    return '';
                }"""
            )
            name = (name or '').strip()
            if name:
                self._emit_log(f'昆仑: 从头像读取到账号名: {name}', 'kunlun')
            return name
        except Exception as e:
            self._emit_log(f'昆仑: 读取展示账号失败: {e}', 'kunlun')
            return ''

    async def identity_matches(self, expected_account: str) -> bool:
        """当前昆仑登录身份是否与网点管家账号一致。"""
        if not (expected_account or '').strip():
            return True
        actual = await self.read_displayed_account()
        if not actual:
            self._emit_log(
                f'昆仑: 无法读取当前登录名，无法与网点管家「{expected_account}」对齐',
                'kunlun',
            )
            return False
        ok = _accounts_match(expected_account, actual)
        if ok:
            self._emit_log(f'昆仑: 账号对齐通过（期望={expected_account}, 实际={actual}）', 'kunlun')
        else:
            self._emit_log(
                f'昆仑: 账号不对齐（期望={expected_account}, 实际={actual}）',
                'kunlun',
            )
        return ok

    async def login(self, *, force_clean: bool = True) -> bool:
        """钉钉 SSO 登录（强制选山东临沂集散中心），最多重试 3 次。

        force_clean=True（默认）：登录前先删 storage_state 并重建 context。
        否则旧 cookie 会让页面直接进旧号，看起来像「登录成功」实则没换号。
        """
        for attempt in range(3):
            try:
                self._emit_log(f'昆仑: 开始登录 (第{attempt + 1}次, force_clean={force_clean})', 'kunlun')
                if not self._browser:
                    raise RuntimeError('昆仑 Browser 未绑定')

                if force_clean or not self._context:
                    await self.invalidate_session('login 前强制清 storage')
                    if not self._context:
                        await self.create_context(self._browser, restore=False)

                if not self._page or self._page.is_closed():
                    self._page = await self._context.new_page()

                try:
                    await login_via_dingtalk(
                        self._page,
                        entry_url=KUNLUN_URL,
                        is_success_url=_is_kunlun_success_url,
                        preferred_org=KUNLUN_ORG,
                        site_label='昆仑',
                    )
                except Exception as e:
                    # 钉钉流程可能因 URL 仍带 ?code= 抛错，但页面其实已进昆仑
                    if not _is_kunlun_host_url(self._page.url):
                        raise
                    self._emit_log(
                        f'昆仑: 钉钉等待抛错但已在昆仑域名，继续等业务壳: {e} | {self._page.url}',
                        'kunlun',
                    )

                if not _is_kunlun_host_url(self._page.url):
                    await self._page.goto(KUNLUN_URL, wait_until='domcontentloaded', timeout=30000)
                    await self._page.wait_for_timeout(3000)

                if not _is_kunlun_host_url(self._page.url):
                    raise RuntimeError(f'登录后仍未进入昆仑: {self._page.url}')

                # SSO 回跳常停在 ?code=...；以搜索按钮为准，最多等 30s
                shell_ok = False
                for i in range(30):
                    if await self._shell_ready():
                        shell_ok = True
                        self._emit_log(
                            f'昆仑: 业务壳已就绪 (第{i + 1}s): {self._page.url}',
                            'kunlun',
                        )
                        break
                    await self._page.wait_for_timeout(1000)

                if not shell_ok:
                    # 带 code 的首页有时壳晚加载：强制进扫描查询再等
                    self._emit_log(
                        f'昆仑: 业务壳未就绪，goto 扫描查询再等: {self._page.url}',
                        'kunlun',
                    )
                    await self._page.goto(KUNLUN_URL, wait_until='domcontentloaded', timeout=30000)
                    await self._page.wait_for_timeout(2000)
                    for i in range(20):
                        if await self._shell_ready():
                            shell_ok = True
                            self._emit_log(
                                f'昆仑: goto 后业务壳就绪 (第{i + 1}s): {self._page.url}',
                                'kunlun',
                            )
                            break
                        await self._page.wait_for_timeout(1000)

                if not shell_ok:
                    raise RuntimeError(f'登录后业务壳未就绪: {self._page.url}')

                # 尽量落到扫描查询入口，方便后续采集（清掉 ?code= 噪音 URL）
                if 'scanQuery' not in (self._page.url or ''):
                    try:
                        await self._page.goto(KUNLUN_URL, wait_until='domcontentloaded', timeout=30000)
                        await self._page.wait_for_timeout(2000)
                    except Exception as e:
                        self._emit_log(f'昆仑: 登录后导航扫描查询失败（忽略）: {e}', 'kunlun')

                await self._context.storage_state(path=KUNLUN_STORAGE_PATH)
                shown = await self.read_displayed_account()
                self._emit_log(
                    f'昆仑: 登录成功，已保存 Session: {self._page.url}，当前账号={shown or "(未读到)"}',
                    'kunlun',
                )
                return True
            except Exception as e:
                self._emit_log(f'昆仑: 登录失败 (第{attempt + 1}次): {e}', 'kunlun')
                # 失败也清一次，避免脏 cookie 污染下一轮
                try:
                    await self.invalidate_session('登录失败清理')
                except Exception:
                    pass
                if attempt < 2:
                    await asyncio.sleep(10)
        return False

    async def open_scan_query(self) -> None:
        """每次采集：点 menu 搜索 → 输入扫描查询 → 点弹窗第一项 → 等面板或 page-info 落地。"""
        await self.ensure_page()
        page = self._page

        if not _is_kunlun_host_url(page.url) or not await self._shell_ready():
            await page.goto(KUNLUN_URL, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(2000)
        elif '?code=' in page.url or '&code=' in page.url:
            # 已登录但 URL 仍带 code：先落到扫描查询再搜
            self._emit_log(f'昆仑: 当前停在 code 回跳页，先 goto 扫描查询: {page.url}', 'kunlun')
            await page.goto(KUNLUN_URL, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(2000)

        self._emit_log('昆仑: 点击 menu 搜索按钮', 'kunlun')
        search_btn = page.locator(KUNLUN_SEARCH_BTN_SELECTOR).first
        await search_btn.wait_for(state='visible', timeout=10000)
        await search_btn.click()
        await page.wait_for_timeout(800)

        search_input = page.locator(KUNLUN_SEARCH_INPUT_SELECTOR).first
        await search_input.wait_for(state='visible', timeout=8000)
        await search_input.fill('')
        await search_input.fill(KUNLUN_SEARCH_KEYWORD)
        self._emit_log(f'昆仑: 已输入「{KUNLUN_SEARCH_KEYWORD}」，等待搜索结果', 'kunlun')
        await page.wait_for_timeout(1200)

        result = page.locator(KUNLUN_SEARCH_RESULT_SELECTOR).first
        await result.wait_for(state='visible', timeout=10000)
        await result.click()
        self._emit_log('昆仑: 已点击搜索结果第一项「扫描查询」', 'kunlun')

        # 落地形态有两种：iframe 面板 或整页 jiutian/page-info
        panel_ok = False
        try:
            panel = page.locator(KUNLUN_SCAN_PANEL_SELECTOR).first
            await panel.wait_for(state='visible', timeout=8000)
            panel_ok = True
            iframe = panel.locator('iframe').first
            try:
                await iframe.wait_for(state='attached', timeout=10000)
            except Exception:
                self._emit_log('昆仑: 扫描查询面板已出现，iframe 等待超时（继续读 token）', 'kunlun')
        except Exception:
            self._emit_log('昆仑: 未出现 iframe 面板，等待 page-info / scanQuery URL 落地', 'kunlun')

        if not panel_ok:
            deadline = asyncio.get_running_loop().time() + 20
            while asyncio.get_running_loop().time() < deadline:
                if _is_scan_query_ready_url(page.url):
                    break
                await page.wait_for_timeout(500)
            else:
                self._emit_log(f'昆仑: URL 未落到扫描查询 ({page.url})，兜底 goto {KUNLUN_URL}', 'kunlun')
                await page.goto(KUNLUN_URL, wait_until='domcontentloaded', timeout=30000)

        await page.wait_for_timeout(2000)
        self._emit_log(f'昆仑: 扫描查询页面就绪: {page.url}', 'kunlun')

    async def _read_sto_token(self) -> str:
        """在 top 与昆仑相关 frames 中读取 sessionStorage.__stoToken。"""
        page = self._page
        if not page or page.is_closed():
            return ''
        script = (
            f"() => {{ try {{ return sessionStorage.getItem('{KUNLUN_SESSION_STORAGE_KEY}') || ''; }} "
            f"catch (e) {{ return ''; }} }}"
        )

        for frame in page.frames:
            try:
                url = frame.url or ''
                if 'kunlun.sto.cn' not in url and frame != page.main_frame:
                    continue
                value = await frame.evaluate(script)
                if value:
                    return value
            except Exception:
                continue

        try:
            value = await page.evaluate(script)
            if value:
                return value
        except Exception:
            pass
        return ''

    async def collect(self) -> list[str]:
        """打开扫描查询后读取 __stoToken，组装 kunlun_stotoken= 上报。"""
        await self.open_scan_query()
        value = ''
        for _ in range(10):
            value = await self._read_sto_token()
            if value:
                break
            await self._page.wait_for_timeout(1000)

        if not value:
            self._emit_log(f'昆仑: ✗ 未读到 sessionStorage.{KUNLUN_SESSION_STORAGE_KEY}', 'kunlun')
            return []

        payload = f'{KUNLUN_REPORT_KEY}={value}'
        self._emit_log(
            f'昆仑: ✓ 命中 {KUNLUN_REPORT_KEY} → 长度 {len(value)} 预览 {value[:24]}...',
            'kunlun',
        )
        return [payload]

    async def keep_alive(self) -> bool:
        """心跳：reload 校验登录态，过期则重登（会清 storage）。"""
        ok = await self.check_session()
        if ok:
            return True
        self._emit_log('昆仑: 心跳发现 Session 无效，尝试重登', 'kunlun')
        return await self.login(force_clean=True)
