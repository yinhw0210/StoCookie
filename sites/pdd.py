import os
import asyncio

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page

from config import (
    PDD_LOGIN_URL,
    PDD_TARGET_URL,
    PDD_COOKIE_DOMAIN,
    PDD_COOKIE_NAME,
    PDD_STORAGE_PATH,
)


class PddSiteDriver:
    name = 'PDD'

    def __init__(self, account: str, password: str, emit_log=None):
        self._account = account
        self._password = password
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._emit_log = emit_log or (lambda msg, cat: logger.info(msg))

    async def create_context(self, browser: Browser) -> BrowserContext:
        if os.path.exists(PDD_STORAGE_PATH):
            self._context = await browser.new_context(storage_state=PDD_STORAGE_PATH)
            self._emit_log('PDD: 恢复已有 Session', 'pdd')
        else:
            self._context = await browser.new_context()
            self._emit_log('PDD: 创建新 Context', 'pdd')
        return self._context

    async def check_session(self) -> bool:
        """检测 session 是否有效。返回 True=有效，False=过期。"""
        try:
            if self._page and not self._page.is_closed():
                self._emit_log('PDD: 复用已有页面检测 Session (reload)', 'pdd')
                await self._page.reload(wait_until='domcontentloaded', timeout=20000)
                await self._page.wait_for_timeout(2000)
            else:
                self._page = await self._context.new_page()
                self._emit_log(f'PDD: 新开页面访问 {PDD_TARGET_URL}', 'pdd')
                await self._page.goto(PDD_TARGET_URL, wait_until='domcontentloaded', timeout=20000)
                await self._page.wait_for_timeout(2000)

            url = self._page.url
            if '/auth/login' in url:
                self._emit_log(f'PDD: Session 过期，跳转到登录页: {url}', 'pdd')
                return False
            self._emit_log(f'PDD: Session 有效，当前 URL: {url}', 'pdd')
            return True
        except Exception as e:
            self._emit_log(f'PDD: Session 检测异常: {e}', 'pdd')
            return False

    async def login(self) -> bool:
        """账号密码登录，最多重试 3 次。"""
        for attempt in range(3):
            try:
                self._emit_log(f'PDD: 开始登录 (第{attempt+1}次)', 'pdd')

                if not self._page or self._page.is_closed():
                    self._page = await self._context.new_page()

                if '/auth/login' not in self._page.url:
                    await self._page.goto(PDD_LOGIN_URL, wait_until='domcontentloaded', timeout=20000)
                    await self._page.wait_for_timeout(2000)

                account_input = self._page.locator('#account')
                password_input = self._page.locator('#password')
                submit_btn = self._page.locator('button[type="submit"]')

                await account_input.fill(self._account)
                await password_input.fill(self._password)
                await self._page.wait_for_timeout(500)
                await submit_btn.click()

                self._emit_log('PDD: 已提交登录表单，等待跳转...', 'pdd')

                for _ in range(30):
                    await self._page.wait_for_timeout(1000)
                    if '/auth/login' not in self._page.url:
                        break
                else:
                    raise RuntimeError('登录后未跳转，可能需要验证码')

                self._emit_log(f'PDD: 登录跳转成功，当前 URL: {self._page.url}', 'pdd')

                if PDD_TARGET_URL not in self._page.url:
                    await self._page.goto(PDD_TARGET_URL, wait_until='domcontentloaded', timeout=20000)
                    await self._page.wait_for_timeout(3000)

                self._emit_log(f'PDD: 已进入目标页面: {self._page.url}', 'pdd')

                await self._context.storage_state(path=PDD_STORAGE_PATH)
                self._emit_log('PDD: 登录成功，已保存 Session', 'pdd')
                return True

            except Exception as e:
                self._emit_log(f'PDD: 登录失败 (第{attempt+1}次): {e}', 'pdd')
                if attempt < 2:
                    await asyncio.sleep(10)
        return False

    async def collect(self) -> list[str]:
        """采集 SUB_PASS_ID cookie。"""
        all_cookies = await self._context.cookies()
        payloads = []

        for c in all_cookies:
            if PDD_COOKIE_DOMAIN in c.get('domain', '') and c['name'] == PDD_COOKIE_NAME:
                payload = f'{c["name"]}={c["value"]}'
                payloads.append(payload)
                self._emit_log(f'PDD: ✓ 命中 {PDD_COOKIE_NAME} → {payload[:60]}', 'pdd')
                break
        else:
            domain_cookies = [c for c in all_cookies if PDD_COOKIE_DOMAIN in c.get('domain', '')]
            if domain_cookies:
                names = [c['name'] for c in domain_cookies]
                self._emit_log(f'PDD: ✗ 未找到 {PDD_COOKIE_NAME}，该域名下有: {", ".join(names)}', 'pdd')
            else:
                self._emit_log(f'PDD: ✗ Context 中无 {PDD_COOKIE_DOMAIN} 域名的 Cookie', 'pdd')

        return payloads

    async def keep_alive(self) -> bool:
        """心跳：reload 目标页面，检查是否仍在登录态。"""
        return await self.check_session()
