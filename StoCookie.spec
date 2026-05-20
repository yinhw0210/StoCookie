import os
import playwright

playwright_dir = os.path.dirname(playwright.__file__)
driver_dir = os.path.join(playwright_dir, 'driver')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        (driver_dir, 'playwright/driver'),
        ('gui/resources', 'gui/resources'),
    ],
    hiddenimports=[
        'pywinauto',
        'pywinauto.controls',
        'pywinauto.controls.uia_controls',
        'pywinauto.uia_defines',
        'apscheduler.schedulers.asyncio',
        'apscheduler.triggers.interval',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StoCookie',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='gui/resources/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StoCookie',
)
