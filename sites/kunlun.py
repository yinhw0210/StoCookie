from __future__ import annotations

import os
import asyncio

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


def _is_kunlun_success_url(url: str) -> bool:
    u = url or ''
    if 'kunlun.sto.cn' not in u or is_auth_url(u):
        return False
    # OAuth 回跳未完成：仍停在 ?code=... 不算已进入业务壳
    if '?code=' in u or '&code=' in u:
        return False
    return True


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
            self._emit_log('昆仑: 恢复已有 Session', 'kunlun')
        else:
            self._context = await browser.new_context(**context_opts)
            self._emit_log('昆仑: 创建新 Context', 'kunlun')
        return self._context

    async def invalidate_session(self, reason: str = '') -> None:
        """清空昆仑独立 context 的 cookie / 落盘状态，强制下次走钉钉重登。
        用于网点管家换号后，避免昆仑继续用旧账号的 storage_state。"""
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
        """reload 检测 session；认证页 / OAuth code 回跳 / 无业务壳 → 过期。"""
        try:
            await self.ensure_page()
            self._emit_log('昆仑: 复用常驻页面检测 Session (reload)', 'kunlun')
            await self._page.reload(wait_until='domcontentloaded', timeout=30000)
            await self._page.wait_for_timeout(3000)
            url = self._page.url
            if not _is_kunlun_success_url(url):
                self._emit_log(f'昆仑: Session 过期或未进入昆仑: {url}', 'kunlun')
                return False
            if not await self._shell_ready():
                self._emit_log(f'昆仑: Session URL 有效但业务壳未就绪: {url}', 'kunlun')
                return False
            self._emit_log(f'昆仑: Session 有效，当前 URL: {url}', 'kunlun')
            return True
        except Exception as e:
            self._emit_log(f'昆仑: Session 检测异常: {e}', 'kunlun')
            return False

    async def read_displayed_account(self) -> str:
        """读取昆仑壳上头像展示名（text 属性），用于与网点管家账号对齐校验。"""
        try:
            await self.ensure_page()
            avatar = self._page.locator('.shell-ui-user-avatar').first
            if not await avatar.is_visible(timeout=2000):
                return ''
            text = (await avatar.get_attribute('text')) or ''
            if not text:
                text = (await avatar.inner_text()) or ''
            return text.strip()
        except Exception:
            return ''

    async def login(self) -> bool:
        """钉钉 SSO 登录（强制选山东临沂集散中心），最多重试 3 次。"""
        for attempt in range(3):
            try:
                self._emit_log(f'昆仑: 开始登录 (第{attempt + 1}次)', 'kunlun')
                if not self._context:
                    if not self._browser:
                        raise RuntimeError('昆仑 Browser 未绑定')
                    await self.create_context(self._browser, restore=False)
                if not self._page or self._page.is_closed():
                    self._page = await self._context.new_page()

                await login_via_dingtalk(
                    self._page,
                    entry_url=KUNLUN_URL,
                    is_success_url=_is_kunlun_success_url,
                    preferred_org=KUNLUN_ORG,
                    site_label='昆仑',
                )

                if not _is_kunlun_success_url(self._page.url):
                    await self._page.goto(KUNLUN_URL, wait_until='domcontentloaded', timeout=30000)
                    await self._page.wait_for_timeout(3000)

                if not _is_kunlun_success_url(self._page.url):
                    raise RuntimeError(f'登录后仍未进入昆仑: {self._page.url}')

                # 等业务壳（搜索）出现，避免停在半登录态
                for _ in range(10):
                    if await self._shell_ready():
                        break
                    await self._page.wait_for_timeout(1000)
                else:
                    raise RuntimeError(f'登录后业务壳未就绪: {self._page.url}')

                await self._context.storage_state(path=KUNLUN_STORAGE_PATH)
                self._emit_log(f'昆仑: 登录成功，已保存 Session: {self._page.url}', 'kunlun')
                return True
            except Exception as e:
                self._emit_log(f'昆仑: 登录失败 (第{attempt + 1}次): {e}', 'kunlun')
                if attempt < 2:
                    await asyncio.sleep(10)
        return False

    async def open_scan_query(self) -> None:
        """每次采集：点 menu 搜索 → 输入扫描查询 → 点弹窗第一项 → 等面板或 page-info 落地。"""
        await self.ensure_page()
        page = self._page

        if not _is_kunlun_success_url(page.url) or not await self._shell_ready():
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

        # 落地形态有两种：
        # 1) shell 内 iframe 面板 div[id="/device/scanQuery"]
        # 2) 整页跳到 /jiutian/page-info/...title=扫描查询（换号后常见）
        # 旧逻辑只等面板 → 第 2 种会 20s 超时，collect 根本读不到 token。
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
                # 最后兜底：直接 goto 入口，再读 token
                self._emit_log(f'昆仑: URL 未落到扫描查询 ({page.url})，兜底 goto {KUNLUN_URL}', 'kunlun')
                await page.goto(KUNLUN_URL, wait_until='domcontentloaded', timeout=30000)

        await page.wait_for_timeout(2000)
        self._emit_log(f'昆仑: 扫描查询页面就绪: {page.url}', 'kunlun')

    async def _read_sto_token(self) -> str:
        """在 top 与昆仑相关 frames 中读取 sessionStorage.__stoToken。"""
        page = self._page
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
        """心跳：reload 校验登录态，过期则重登。"""
        ok = await self.check_session()
        if ok:
            return True
        self._emit_log('昆仑: 心跳发现 Session 无效，尝试重登', 'kunlun')
        return await self.login()
