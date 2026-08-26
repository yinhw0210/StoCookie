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
    return 'kunlun.sto.cn' in (url or '') and not is_auth_url(url)


class KunlunSiteDriver:
    name = '昆仑'

    def __init__(self, emit_log=None):
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._emit_log = emit_log or (lambda msg, cat: logger.info(msg))

    async def create_context(self, browser: Browser) -> BrowserContext:
        context_opts = {'no_viewport': True}
        if os.path.exists(KUNLUN_STORAGE_PATH):
            context_opts['storage_state'] = KUNLUN_STORAGE_PATH
            self._context = await browser.new_context(**context_opts)
            self._emit_log('昆仑: 恢复已有 Session', 'kunlun')
        else:
            self._context = await browser.new_context(**context_opts)
            self._emit_log('昆仑: 创建新 Context', 'kunlun')
        return self._context

    async def ensure_page(self):
        """确保常驻页面存在；不存在则新建并导航到昆仑扫描查询入口。"""
        if self._page and not self._page.is_closed():
            return
        self._page = await self._context.new_page()
        self._emit_log(f'昆仑: 新开常驻页面，导航到 {KUNLUN_URL}', 'kunlun')
        await self._page.goto(KUNLUN_URL, wait_until='domcontentloaded', timeout=30000)
        await self._page.wait_for_timeout(3000)

    async def check_session(self) -> bool:
        """reload 检测 session；落到认证页则视为过期。"""
        try:
            await self.ensure_page()
            self._emit_log('昆仑: 复用常驻页面检测 Session (reload)', 'kunlun')
            await self._page.reload(wait_until='domcontentloaded', timeout=30000)
            await self._page.wait_for_timeout(3000)
            url = self._page.url
            if is_auth_url(url) or 'kunlun.sto.cn' not in url:
                self._emit_log(f'昆仑: Session 过期或未进入昆仑: {url}', 'kunlun')
                return False
            self._emit_log(f'昆仑: Session 有效，当前 URL: {url}', 'kunlun')
            return True
        except Exception as e:
            self._emit_log(f'昆仑: Session 检测异常: {e}', 'kunlun')
            return False

    async def login(self) -> bool:
        """钉钉 SSO 登录（强制选山东临沂集散中心），最多重试 3 次。"""
        for attempt in range(3):
            try:
                self._emit_log(f'昆仑: 开始登录 (第{attempt + 1}次)', 'kunlun')
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

                if is_auth_url(self._page.url) or 'kunlun.sto.cn' not in self._page.url:
                    raise RuntimeError(f'登录后仍未进入昆仑: {self._page.url}')

                await self._context.storage_state(path=KUNLUN_STORAGE_PATH)
                self._emit_log(f'昆仑: 登录成功，已保存 Session: {self._page.url}', 'kunlun')
                return True
            except Exception as e:
                self._emit_log(f'昆仑: 登录失败 (第{attempt + 1}次): {e}', 'kunlun')
                if attempt < 2:
                    await asyncio.sleep(10)
        return False

    async def open_scan_query(self) -> None:
        """每次采集：点 menu 搜索 → 输入扫描查询 → 点弹窗第一项 → 等待扫描查询面板/iframe。"""
        await self.ensure_page()
        page = self._page

        if 'kunlun.sto.cn' not in page.url or is_auth_url(page.url):
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

        panel = page.locator(KUNLUN_SCAN_PANEL_SELECTOR).first
        await panel.wait_for(state='visible', timeout=20000)
        iframe = panel.locator('iframe').first
        try:
            await iframe.wait_for(state='attached', timeout=15000)
        except Exception:
            self._emit_log('昆仑: 扫描查询面板已出现，iframe 等待超时（继续读 token）', 'kunlun')
        await page.wait_for_timeout(2000)
        self._emit_log(f'昆仑: 扫描查询页面就绪: {page.url}', 'kunlun')

    async def _read_sto_token(self) -> str:
        """在 top 与昆仑相关 frames 中读取 sessionStorage.__stoToken。"""
        page = self._page
        script = (
            f"() => {{ try {{ return sessionStorage.getItem('{KUNLUN_SESSION_STORAGE_KEY}') || ''; }} "
            f"catch (e) {{ return ''; }} }}"
        )

        # 优先 iframe / 子 frame
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
        # SPA 异步写入，短轮询
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
