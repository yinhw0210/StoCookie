import asyncio
from playwright.async_api import Page, Frame
from loguru import logger

from config import (
    LOGIN_ENTRY_URL,
    ROLE_ENTRY_BUTTON_SELECTOR,
    ROLE_ITEM_SELECTOR,
    ROLE_PAGE_SELECTOR,
    SAFETY_QUICK_LOGIN_SELECTOR,
    SSO_URL,
    WANGDIAN_INDEX_URL,
    is_logged_in_url,
)
from desktop_automation import click_dingtalk_confirm


async def _has_dingtalk_frame(page: Page) -> bool:
    """快速检测页面是否包含钉钉登录 iframe（不抛异常）"""
    return any(
        'login.dingtalk.com/oauth2/challenge' in f.url
        for f in page.frames
    )


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


async def _finish_confirm_task(task: asyncio.Task) -> None:
    if task.done():
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f'桌面确认任务已结束: {e}')
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.debug(f'桌面确认任务取消时结束: {e}')


async def _do_dingtalk_login_flow(page: Page) -> None:
    """执行钉钉 iframe 登录子流程（定位 iframe、点击头像、确认登录等）"""
    dd_frame = await _get_dingtalk_frame(page)
    logger.info(f'[dingtalk_flow] 已定位钉钉 iframe: {dd_frame.url}')
    await _dismiss_cookie_dialog(dd_frame)

    confirm_task = asyncio.create_task(click_dingtalk_confirm(timeout=30))
    try:
        await _click_avatar(dd_frame)
        await _click_confirm_login(dd_frame)
        await _click_consent(dd_frame)
    finally:
        await _finish_confirm_task(confirm_task)


async def select_first_role_if_present(page: Page) -> bool:
    """如果出现多角色选择页，选择第一个角色并点击进入系统。"""
    role_page = page.locator(ROLE_PAGE_SELECTOR)
    role_items = page.locator(ROLE_ITEM_SELECTOR)

    has_role_page = False
    try:
        has_role_page = await role_page.first.is_visible(timeout=1000)
    except Exception:
        pass

    has_role_item = False
    try:
        has_role_item = await role_items.first.is_visible(timeout=1000)
    except Exception:
        pass

    if not has_role_page and not has_role_item:
        return False

    try:
        await role_items.first.wait_for(state='visible', timeout=5000)
    except Exception:
        raise RuntimeError('检测到角色选择页，但未找到可选角色')

    await role_items.first.click()
    logger.info('已选择第一个关联工号')

    entry_button = page.locator(ROLE_ENTRY_BUTTON_SELECTOR)
    if not await entry_button.first.is_visible(timeout=5000):
        raise RuntimeError('未找到「进入系统」按钮')

    await entry_button.first.click()
    logger.info('已点击「进入系统」')
    await page.wait_for_url(
        lambda url: is_logged_in_url(url),
        timeout=30000,
    )
    return True


async def click_safety_quick_login_if_present(page: Page) -> bool:
    """如果出现虎盾零信任快速登录页，点击快速登录继续。"""
    if 'safety-tsportal.sto.cn' not in page.url:
        return False

    quick_login = page.locator(SAFETY_QUICK_LOGIN_SELECTOR)
    try:
        if not await quick_login.first.is_visible(timeout=3000):
            return False
    except Exception:
        return False

    await quick_login.first.click()
    logger.info('已点击虎盾「快速登录」')
    return True


async def wait_for_wangdian_entry_or_role(page: Page, timeout_ms: int = 60000) -> None:
    """等待进入网点系统；必要时处理虎盾快速登录和角色选择页。"""
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    dingtalk_attempted = False

    while asyncio.get_running_loop().time() < deadline:
        if is_logged_in_url(page.url):
            logger.info(f'已进入网点系统: {page.url}')
            return

        if await click_safety_quick_login_if_present(page):
            await page.wait_for_timeout(2000)
            continue

        # 检测钉钉 iframe 并执行登录
        if not dingtalk_attempted and await _has_dingtalk_frame(page):
            logger.info('[wait] 检测到钉钉 iframe，执行钉钉登录流程')
            dingtalk_attempted = True
            try:
                await _do_dingtalk_login_flow(page)
                await page.wait_for_timeout(3000)
            except Exception as e:
                logger.warning(f'[wait] 钉钉登录流程异常: {e}')
            continue

        if await select_first_role_if_present(page):
            if is_logged_in_url(page.url):
                logger.info(f'选择角色后已进入网点系统: {page.url}')
                return

        await page.wait_for_timeout(1000)

    logger.error(f'等待进入网点系统超时，当前 URL: {page.url}')
    try:
        content = await page.locator('body').inner_text(timeout=3000)
        logger.error(f'当前页面内容: {content[:500]}')
    except Exception:
        pass
    raise RuntimeError(f'登录未完成，未进入 {LOGIN_ENTRY_URL} 或 {WANGDIAN_INDEX_URL}')


wait_for_wangdian_index_or_role = wait_for_wangdian_entry_or_role


async def login_via_dingtalk(page: Page, skip_navigate: bool = False) -> bool:
    """
    完整登录流程：
    1. 打开网点系统入口（如果 skip_navigate=True 则跳过，直接在当前页面操作）
    2. 定位钉钉 iframe
    3. 关闭 Cookie 弹窗（iframe 内）
    4. 点击用户头像
    5. 点击「立即登录」
    6. 处理授权同意（如有）
    7. 等待进入网点首页，如出现虎盾或角色选择则自动处理
    """
    logger.info('开始钉钉登录...')

    if not skip_navigate:
        await page.goto(SSO_URL)
        await page.wait_for_timeout(3000)

        if is_logged_in_url(page.url):
            logger.info(f'网点系统入口未跳转认证页，已登录: {page.url}')
            return True

    if await click_safety_quick_login_if_present(page):
        await page.wait_for_timeout(2000)
        await wait_for_wangdian_entry_or_role(page)
        logger.info('钉钉登录成功')
        return True

    # Step 1: 定位钉钉 iframe
    dd_frame = await _get_dingtalk_frame(page)
    logger.info(f'已定位钉钉 iframe: {dd_frame.url}')

    # Step 2: 关闭 Cookie 弹窗
    await _dismiss_cookie_dialog(dd_frame)

    # Step 3: 先启动桌面自动化，再点击头像触发钉钉客户端确认弹窗
    confirm_task = asyncio.create_task(click_dingtalk_confirm(timeout=30))
    try:
        await _click_avatar(dd_frame)

        # Step 4: 点击「立即登录」或等待钉钉客户端确认
        await _click_confirm_login(dd_frame)

        # Step 5: 处理授权同意页面
        await _click_consent(dd_frame)

        # Step 6: 等待进入系统首页；虎盾和多角色账号会自动处理
        await wait_for_wangdian_entry_or_role(page)
    except Exception as e:
        logger.debug(f'钉钉登录流程中断: {e}')
        raise
    finally:
        await _finish_confirm_task(confirm_task)

    logger.info('钉钉登录成功')
    return True
