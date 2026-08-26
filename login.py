from __future__ import annotations

import asyncio
from playwright.async_api import Page, Frame
from loguru import logger

from config import (
    LOGIN_ENTRY_URL,
    ROLE_ACTIVE_CLASS,
    ROLE_ENTRY_BUTTON_SELECTOR,
    ROLE_ITEM_SELECTOR,
    ROLE_PAGE_SELECTOR,
    SAFETY_QUICK_LOGIN_SELECTOR,
    SSO_URL,
    WANGDIAN_INDEX_URL,
    is_logged_in_url,
    preferred_role_org,
)
from desktop_automation import click_dingtalk_confirm


async def _has_dingtalk_frame(page: Page) -> bool:
    """快速检测页面是否包含钉钉登录 iframe（不抛异常）"""
    return any(
        'login.dingtalk.com/oauth2/challenge' in f.url
        for f in page.frames
    )


async def _get_dingtalk_frame(page: Page, retries: int = 6) -> Frame:
    """定位钉钉 OAuth2 iframe。登录页加载较慢（app_login 页可能需 10s+ 才渲染出 iframe），
    重试 6 次 × 2s ≈ 12s，避免加载慢被误判为「未找到钉钉登录 iframe」。"""
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
    """点击用户头像触发登录确认流程（带重试，应对加载慢的情况）"""
    avatar = frame.locator('.module-qrcode-user-avatar')
    for attempt in range(3):
        try:
            if await avatar.first.is_visible(timeout=5000):
                await avatar.first.click()
                logger.info('已点击用户头像')
                await frame.page.wait_for_timeout(1500)
                return
        except Exception:
            pass
        if attempt < 2:
            logger.info(f'头像未加载，{3-attempt}s 后重试...')
            await frame.page.wait_for_timeout(3000)
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


async def _list_visible_orgs(page: Page) -> list[str]:
    """收集选择工号页上可见的所属组织文案，便于失败诊断。"""
    items = page.locator(ROLE_ITEM_SELECTOR)
    orgs: list[str] = []
    try:
        count = await items.count()
        for i in range(count):
            text = (await items.nth(i).inner_text(timeout=2000) or '').strip()
            for line in text.splitlines():
                line = line.strip()
                if line.startswith('所属组织:'):
                    orgs.append(line.replace('所属组织:', '').strip())
                    break
    except Exception:
        pass
    return orgs


async def _click_role_item_by_org(page: Page, org: str) -> None:
    """按所属组织点击工号项，并校验出现选中态；失败抛错。"""
    items = page.locator(ROLE_ITEM_SELECTOR)
    await items.first.wait_for(state='visible', timeout=8000)
    count = await items.count()
    target = None
    for i in range(count):
        item = items.nth(i)
        text = await item.inner_text(timeout=3000)
        # HTML 里常有「所属组织: 山东临沂公司  」尾部空格，做归一化匹配
        normalized = ' '.join(text.replace('\u00a0', ' ').split())
        if f'所属组织: {org}' in normalized:
            target = item
            break
    if target is None:
        visible = await _list_visible_orgs(page)
        raise RuntimeError(f'未找到所属组织「{org}」的工号项，页面可见组织: {visible}')

    for attempt in range(2):
        await target.click()
        await page.wait_for_timeout(500)
        cls = (await target.get_attribute('class')) or ''
        if ROLE_ACTIVE_CLASS in cls:
            logger.info(f'已按所属组织选择: {org} (选中态已确认)')
            return
        logger.warning(f'所属组织「{org}」点击后未出现选中态，重试 ({attempt + 1}/2)')
        await page.wait_for_timeout(500)

    cls = (await target.get_attribute('class')) or ''
    raise RuntimeError(f'所属组织「{org}」未能选中 (class={cls!r})')


async def _select_first_role_and_enter(page: Page, preferred_org: str | None = None) -> bool:
    """检测角色/工号选择页，按站点绑定的所属组织选中后再点「进入系统」。
    preferred_org 非空时强制使用该组织（用于昆仑等独立站点登录中间页 host 非目标站的情况）。
    返回 True 表示检测到角色页并已点击；无角色页返回 False。
    注意：不等待特定 URL，由调用方决定后续等待逻辑（适用于 wangdian 及其他页面）。"""
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

    org = preferred_org or preferred_role_org(page.url)
    logger.info(f'检测到选择工号页，目标所属组织: {org} (url={page.url})')
    await _click_role_item_by_org(page, org)

    entry_button = page.locator(ROLE_ENTRY_BUTTON_SELECTOR)
    if not await entry_button.first.is_visible(timeout=5000):
        raise RuntimeError('未找到「进入系统」按钮')

    await entry_button.first.click()
    logger.info(f'已点击「进入系统」(所属组织={org})')
    return True


async def select_role_if_present(
    page: Page,
    *,
    preferred_org: str | None = None,
    is_success_url=None,
) -> bool:
    """如果出现多角色选择页，按所属组织选择并进入；成功后等待 is_success_url（默认网点管家）。"""
    handled = await _select_first_role_and_enter(page, preferred_org=preferred_org)
    if not handled:
        return False
    success = is_success_url or is_logged_in_url
    await page.wait_for_url(success, timeout=30000)
    return True


async def select_first_role_if_present(page: Page) -> bool:
    """兼容旧调用：按所属组织选择并等待进入 wangdian。"""
    return await select_role_if_present(page)


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


async def wait_for_site_entry_or_role(
    page: Page,
    *,
    is_success_url=None,
    preferred_org: str | None = None,
    timeout_ms: int = 120000,
    site_label: str = '目标站点',
) -> None:
    """等待进入目标站点；必要时处理虎盾、钉钉 iframe、角色选择页。
    is_success_url(url)->bool 判定成功；默认 is_logged_in_url（网点管家）。"""
    success = is_success_url or is_logged_in_url
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    dingtalk_attempted = False

    while asyncio.get_running_loop().time() < deadline:
        if success(page.url):
            logger.info(f'已进入{site_label}: {page.url}')
            return

        if await click_safety_quick_login_if_present(page):
            await page.wait_for_timeout(2000)
            continue

        if not dingtalk_attempted and await _has_dingtalk_frame(page):
            logger.info('[wait] 检测到钉钉 iframe，执行钉钉登录流程')
            dingtalk_attempted = True
            try:
                await _do_dingtalk_login_flow(page)
                await page.wait_for_timeout(3000)
            except Exception as e:
                logger.warning(f'[wait] 钉钉登录流程异常: {e}')
            continue

        try:
            handled = await _select_first_role_and_enter(page, preferred_org=preferred_org)
            if handled:
                await page.wait_for_timeout(2000)
                if success(page.url):
                    logger.info(f'选择角色后已进入{site_label}: {page.url}')
                    return
                continue
        except Exception as e:
            logger.warning(f'[wait] 角色选择异常: {e}')

        await page.wait_for_timeout(1000)

    logger.error(f'等待进入{site_label}超时，当前 URL: {page.url}')
    try:
        content = await page.locator('body').inner_text(timeout=3000)
        logger.error(f'当前页面内容: {content[:500]}')
    except Exception:
        pass
    raise RuntimeError(f'登录未完成，未进入{site_label}，当前 URL: {page.url}')


async def wait_for_wangdian_entry_or_role(page: Page, timeout_ms: int = 120000) -> None:
    """等待进入网点系统；必要时处理虎盾快速登录和角色选择页。"""
    await wait_for_site_entry_or_role(
        page,
        is_success_url=is_logged_in_url,
        timeout_ms=timeout_ms,
        site_label='网点系统',
    )


wait_for_wangdian_index_or_role = wait_for_wangdian_entry_or_role


async def login_via_dingtalk(
    page: Page,
    skip_navigate: bool = False,
    *,
    entry_url: str | None = None,
    is_success_url=None,
    preferred_org: str | None = None,
    site_label: str = '网点系统',
) -> bool:
    """
    完整登录流程：
    1. 打开入口（默认网点管家；可传 entry_url 如昆仑）
    2. 定位钉钉 iframe / 虎盾
    3. 选择工号（可强制 preferred_org）
    4. 等待 is_success_url（默认网点管家已登录 URL）
    """
    from config import is_auth_url as _is_auth

    logger.info(f'开始钉钉登录... ({site_label})')
    success = is_success_url or is_logged_in_url
    target = entry_url or SSO_URL

    if not skip_navigate:
        await page.goto(target)
        await page.wait_for_timeout(3000)
        logger.info(f'[登录] goto 后 URL: {page.url}')
        try:
            cookies = await page.context.cookies(['https://wangdian.sto.cn', 'https://page.sto.cn', 'https://kunlun.sto.cn'])
            names = sorted(c['name'] for c in cookies)
            logger.info(f'[登录] goto 后相关域 cookie: {names}')
        except Exception as e:
            logger.warning(f'[登录] 读取 cookie 失败: {e}')

        if success(page.url) and not _is_auth(page.url):
            logger.info(f'{site_label}入口未跳转认证页，已登录: {page.url}')
            return True

    if await click_safety_quick_login_if_present(page):
        await page.wait_for_timeout(2000)
        await wait_for_site_entry_or_role(
            page,
            is_success_url=success,
            preferred_org=preferred_org,
            site_label=site_label,
        )
        logger.info(f'钉钉登录成功 ({site_label})')
        return True

    dd_frame = await _get_dingtalk_frame(page)
    logger.info(f'已定位钉钉 iframe: {dd_frame.url}')

    await _dismiss_cookie_dialog(dd_frame)

    confirm_task = asyncio.create_task(click_dingtalk_confirm(timeout=30))
    try:
        await _click_avatar(dd_frame)
        await _click_confirm_login(dd_frame)
        await _click_consent(dd_frame)
        await wait_for_site_entry_or_role(
            page,
            is_success_url=success,
            preferred_org=preferred_org,
            site_label=site_label,
        )
    except Exception as e:
        logger.debug(f'钉钉登录流程中断: {e}')
        raise
    finally:
        await _finish_confirm_task(confirm_task)

    logger.info(f'[登录] 流程结束 URL: {page.url}')
    try:
        cookies = await page.context.cookies()
        sto_names = sorted(c['name'] for c in cookies if 'sto.cn' in c.get('domain', ''))
        logger.info(f'[登录] sto 域 cookie: {sto_names}')
    except Exception as e:
        logger.warning(f'[登录] 读取 cookie 失败: {e}')

    logger.info(f'钉钉登录成功 ({site_label})')
    return True
