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
    from pywinauto import Application

    start = time.time()
    while time.time() - start < timeout:
        try:
            app = Application(backend='uia').connect(title_re='.*钉钉.*|.*DingTalk.*')
            dlg = app.window(title_re='.*确认.*|.*登录.*|.*Confirm.*')
            btn = dlg.child_window(
                title_re='.*确认.*|.*同意.*|.*允许.*|.*Confirm.*',
                control_type='Button'
            )
            btn.click()
            logger.info('pywinauto 成功点击钉钉确认按钮')
            return True
        except Exception:
            time.sleep(1)
    raise TimeoutError('pywinauto 未能点击钉钉确认按钮')
