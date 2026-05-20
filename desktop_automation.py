import asyncio
import platform
from loguru import logger


async def click_dingtalk_confirm(timeout: int = 30) -> bool:
    if platform.system() == 'Darwin':
        return await _confirm_macos(timeout)
    elif platform.system() == 'Windows':
        return await _confirm_windows(timeout)
    else:
        raise RuntimeError(f'不支持的平台: {platform.system()}')


async def _confirm_macos(timeout: int) -> bool:
    """
    钉钉确认弹窗结构（实测确认）：
    window 1（无名窗口，440x528）
      → group 1 → group 1 → scroll area 1 → WebArea
        → group 1 → group 1 → group 1 (contentGroup)
          - image (头像)
          - group 1: "单点登录"
          - group 2: "登录" ← 点击目标，AXGroup 有 AXPress action
          - group 3: "取消登录"
    """
    script = '''
    tell application "System Events"
        tell process "DingTalk"
            repeat %d times
                try
                    set w to window 1
                    if name of w is "" then
                        set g1 to group 1 of w
                        set g11 to group 1 of g1
                        set sa to scroll area 1 of g11
                        set wa to UI element 1 of sa
                        set topGroup to group 1 of wa
                        set innerGroup to group 1 of topGroup
                        set contentGroup to group 1 of innerGroup
                        set loginGroup to group 2 of contentGroup
                        set loginText to value of static text 1 of loginGroup
                        if loginText is "登录" then
                            perform action "AXPress" of loginGroup
                            return "success"
                        end if
                    end if
                end try
                delay 1
            end repeat
        end tell
    end tell
    return "timeout"
    ''' % timeout

    proc = await asyncio.create_subprocess_exec(
        'osascript', '-e', script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    result = stdout.decode().strip()
    if result != 'success':
        logger.warning(f'AppleScript 确认失败: stdout={result}, stderr={stderr.decode()}')
        raise TimeoutError('AppleScript 未能点击钉钉确认按钮')
    logger.info('AppleScript 成功点击钉钉「登录」按钮')
    return True


async def _confirm_windows(timeout: int) -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_click_windows, timeout)


def _do_click_windows(timeout: int) -> bool:
    import time
    from pywinauto import Desktop, mouse

    start = time.time()
    desktop = Desktop(backend='uia')
    logged_windows = set()
    while time.time() - start < timeout:
        for dlg in _find_dingtalk_confirm_windows(desktop):
            summary = _window_summary(dlg)
            if summary not in logged_windows:
                logged_windows.add(summary)
                logger.info(f'发现疑似钉钉确认弹窗: {summary}')
                _log_window_controls(dlg)

            if _click_login_control(dlg):
                logger.info('pywinauto 已通过 UIA 控件点击钉钉「登录」')
                return True

            if _click_login_coordinates(dlg, mouse):
                logger.info('pywinauto 已通过弹窗坐标兜底点击钉钉「登录」')
                return True

        time.sleep(0.3)

    logger.warning(f'Windows 顶层窗口快照: {_top_window_snapshot(desktop)}')
    raise TimeoutError('pywinauto 未能点击钉钉确认按钮')


def _find_dingtalk_confirm_windows(desktop):
    candidates = []
    for win in desktop.windows():
        try:
            if not win.is_visible():
                continue
            rect = win.rectangle()
            width = rect.width()
            height = rect.height()
            if width <= 0 or height <= 0:
                continue

            title = win.window_text() or ''
            class_name = win.class_name() or ''
            title_or_class_matches = any(
                marker in f'{title} {class_name}'
                for marker in ('钉钉', 'DingTalk', 'Ding')
            )
            popup_sized = 320 <= width <= 720 and 360 <= height <= 820

            if title_or_class_matches or popup_sized:
                names = _control_names(win)
                has_confirm_text = (
                    '单点登录' in names
                    and '登录' in names
                    and ('取消登录' in names or '取消' in names)
                )
                if has_confirm_text:
                    candidates.append(win)
                    continue

            if title_or_class_matches and popup_sized:
                candidates.append(win)
        except Exception as e:
            logger.debug(f'跳过窗口失败: {e}')

    return candidates


def _click_login_control(dlg) -> bool:
    for control in _find_login_controls(dlg):
        logger.debug(f'尝试点击登录控件: {_control_summary(control)}')
        for target in _clickable_chain(control):
            try:
                invoke = getattr(target, 'invoke', None)
                if callable(invoke):
                    invoke()
                    return True
            except Exception as e:
                logger.debug(f'Invoke 登录控件失败: {_control_summary(target)} err={e}')

            try:
                target.click_input()
                return True
            except Exception as e:
                logger.debug(f'click_input 登录控件失败: {_control_summary(target)} err={e}')

    return False


def _find_login_controls(dlg):
    controls = []
    try:
        descendants = dlg.descendants()
    except Exception as e:
        logger.debug(f'读取弹窗 UIA 子控件失败: {e}')
        return controls

    for control in descendants:
        name = _control_name(control)
        if name == '登录':
            controls.append(control)

    controls.sort(key=_control_center_y, reverse=True)
    return controls


def _clickable_chain(control, limit: int = 4):
    current = control
    for _ in range(limit):
        if current is None:
            return
        yield current
        try:
            current = current.parent()
        except Exception:
            return


def _click_login_coordinates(dlg, mouse) -> bool:
    names = _control_names(dlg)
    if '单点登录' not in names or '登录' not in names:
        return False

    try:
        rect = dlg.rectangle()
        x = rect.left + int(rect.width() * 0.5)
        y = rect.top + int(rect.height() * 0.76)
        mouse.click(button='left', coords=(x, y))
        logger.debug(f'坐标兜底点击: x={x}, y={y}, window={_window_summary(dlg)}')
        return True
    except Exception as e:
        logger.debug(f'坐标兜底点击失败: {e}')
        return False


def _control_names(dlg):
    names = set()
    try:
        controls = dlg.descendants()
    except Exception:
        controls = []

    for control in controls:
        name = _control_name(control)
        if name:
            names.add(name)
    return names


def _control_name(control) -> str:
    try:
        name = control.window_text()
        if name:
            return name.strip()
    except Exception:
        pass

    try:
        name = control.element_info.name
        if name:
            return name.strip()
    except Exception:
        pass

    return ''


def _control_center_y(control) -> int:
    try:
        rect = control.rectangle()
        return rect.top + rect.height() // 2
    except Exception:
        return 0


def _window_summary(win) -> str:
    try:
        rect = win.rectangle()
        rect_text = f'{rect.left},{rect.top},{rect.width()}x{rect.height()}'
    except Exception:
        rect_text = 'unknown-rect'

    return (
        f'title={win.window_text()!r}, '
        f'class={win.class_name()!r}, '
        f'rect={rect_text}'
    )


def _control_summary(control) -> str:
    try:
        info = control.element_info
        control_type = info.control_type
        automation_id = info.automation_id
        class_name = info.class_name
    except Exception:
        control_type = 'unknown'
        automation_id = ''
        class_name = ''

    try:
        rect = control.rectangle()
        rect_text = f'{rect.left},{rect.top},{rect.width()}x{rect.height()}'
    except Exception:
        rect_text = 'unknown-rect'

    return (
        f'name={_control_name(control)!r}, '
        f'type={control_type!r}, '
        f'automation_id={automation_id!r}, '
        f'class={class_name!r}, '
        f'rect={rect_text}'
    )


def _log_window_controls(dlg) -> None:
    try:
        controls = [
            _control_summary(control)
            for control in dlg.descendants()
            if _control_name(control)
        ]
    except Exception as e:
        logger.debug(f'无法打印弹窗 UIA 控件摘要: {e}')
        return

    logger.debug('钉钉弹窗 UIA 控件摘要:\n' + '\n'.join(controls[:80]))


def _top_window_snapshot(desktop) -> str:
    rows = []
    for win in desktop.windows():
        try:
            rows.append(_window_summary(win))
        except Exception:
            continue
    return ' | '.join(rows[:40])
