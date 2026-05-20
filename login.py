import asyncio
from playwright.async_api import Page, Frame
from loguru import logger

from config import SSO_URL
from desktop_automation import click_dingtalk_confirm


async def _get_dingtalk_frame(page: Page, retries: int = 3) -> Frame:
    """定位钉钉 OAuth2 iframe"""
    for i in range(retries):
        dd_frame = next(
            (f for f in page.frames if 'login.dingtalk.com/oauth2/challenge' in f.url),
            None
        )
        if dd_frame:
            return dd_frame
        await page.wait_for_timeout(2000)

    logger.error('未找到钉钉登录 iframe，当前 frames:')
    for f in page.frames:
        logger.error(f'  - {f.url}')
    raise RuntimeError('未找到钉钉登录 iframe')


async def _dismiss_cookie_dialog(frame: Frame) -> None:
    """
    处理钉钉 iframe 内的 Cookie/协议弹窗。
    弹窗外层 .module-pass-login-op-protocol-modal 的 footer 会拦截 pointer events，
    导致 Playwright 普通 click 超时，必须用 JS evaluate 直接点击。
    """
    try:
        modal = frame.locator('.module-pass-login-op-protocol-modal')
        if await modal.is_visible(timeout=3000):
            result = await frame.evaluate('''() => {
                const modal = document.querySelector('.module-pass-login-op-protocol-modal');
                if (!modal) return 'no modal';
                const footer = modal.querySelector('.base-comp-model-footer');
                if (!footer) return 'no footer';
                const buttons = footer.querySelectorAll('.base-comp-button');
                for (const btn of buttons) {
                    if (btn.textContent.trim().includes('确定')) {
                        btn.click();
                        return 'success';
                    }
                }
                return 'no confirm btn';
            }''')
            logger.info(f'Cookie 弹窗处理: {result}')
            await frame.page.wait_for_timeout(1500)
    except Exception as e:
        logger.debug(f'Cookie 弹窗检测: {e}')


async def _click_avatar(frame: Frame) -> None:
    """点击用户头像触发登录确认流程"""
    avatar = frame.locator('.module-qrcode-user-avatar')
    if await avatar.first.is_visible(timeout=5000):
        await avatar.first.click()
        logger.info('已点击用户头像')
        await frame.page.wait_for_timeout(1500)
    else:
        raise RuntimeError('未找到用户头像')


async def _click_confirm_login(frame: Frame) -> None:
    """点击「立即登录」按钮（module-confirm 页面）"""
    btn = frame.locator('.module-confirm-button')
    try:
        if await btn.is_visible(timeout=5000):
            await btn.click()
            logger.info('已点击「立即登录」')
            return
    except Exception:
        pass

    # 备选：module-qrscan-login-btn（扫码确认页面的登录按钮）
    btn2 = frame.locator('.module-qrscan-login-btn')
    try:
        if await btn2.is_visible(timeout=3000):
            await btn2.click()
            logger.info('已点击扫码确认「登录」')
            return
    except Exception:
        pass

    # 备选：module-localscan-login-btn
    btn3 = frame.locator('.module-localscan-login-btn')
    try:
        if await btn3.is_visible(timeout=3000):
            await btn3.click()
            logger.info('已点击本地扫码「登录」')
            return
    except Exception:
        pass

    logger.warning('未找到确认登录按钮，可能需要钉钉客户端确认')


async def _click_consent(frame: Frame) -> None:
    """处理授权同意页面"""
    agree_btn = frame.locator('.module-consent-submit-agree')
    try:
        if await agree_btn.is_visible(timeout=5000):
            await agree_btn.click()
            logger.info('已点击授权「同意」')
    except Exception:
        logger.debug('未出现授权同意页面')


async def login_via_dingtalk(page: Page) -> bool:
    """
    完整登录流程：
    1. 打开 SSO 页面
    2. 定位钉钉 iframe
    3. 关闭 Cookie 弹窗（iframe 内）
    4. 点击用户头像
    5. 点击「立即登录」
    6. 处理授权同意（如有）
    7. 等待页面跳转
    """
    logger.info('开始钉钉登录...')
    await page.goto(SSO_URL)
    await page.wait_for_timeout(3000)

    # Step 1: 定位钉钉 iframe
    dd_frame = await _get_dingtalk_frame(page)
    logger.info(f'已定位钉钉 iframe: {dd_frame.url}')

    # Step 2: 关闭 Cookie 弹窗
    await _dismiss_cookie_dialog(dd_frame)

    # Step 3: 点击用户头像
    await _click_avatar(dd_frame)

    # Step 4: 点击「立即登录」或等待钉钉客户端确认
    await _click_confirm_login(dd_frame)

    # Step 5: 同时启动桌面自动化（钉钉客户端可能弹确认框）
    confirm_task = asyncio.create_task(click_dingtalk_confirm(timeout=30))

    # Step 6: 处理授权同意页面
    await _click_consent(dd_frame)

    # Step 7: 等待页面跳转（登录成功）
    try:
        await page.wait_for_url(
            lambda url: 'sto-sso-web' not in url,
            timeout=40000
        )
    except Exception as e:
        confirm_task.cancel()
        logger.error(f'登录跳转超时: {e}')
        # 打印当前状态帮助调试
        logger.error(f'当前 URL: {page.url}')
        try:
            content = await dd_frame.text_content('body')
            logger.error(f'iframe 内容: {content[:500]}')
        except Exception:
            pass
        raise

    confirm_task.cancel()
    logger.info('钉钉登录成功')
    return True
