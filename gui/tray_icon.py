from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QCoreApplication

from config import BASE_DIR
import os


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window, worker, parent=None):
        icon_path = os.path.join(BASE_DIR, 'gui', 'resources', 'icon.ico')
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
        else:
            icon = QIcon()
        super().__init__(icon, parent)

        self._window = window
        self._worker = worker

        menu = QMenu()
        show_action = QAction('显示主窗口', menu)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        sync_action = QAction('立即同步', menu)
        sync_action.triggered.connect(self._worker.trigger_sync)
        menu.addAction(sync_action)

        menu.addSeparator()

        self._pause_action = QAction('暂停', menu)
        self._pause_action.triggered.connect(self._toggle_pause)
        menu.addAction(self._pause_action)

        menu.addSeparator()

        quit_action = QAction('退出', menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self.setToolTip('StoCookie')

    def _show_window(self):
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _toggle_pause(self):
        if self._pause_action.text() == '暂停':
            self._worker.pause()
            self.set_paused(True)
            # 同步主窗口 UI（若已绑定）
            if hasattr(self._window, 'set_paused_ui'):
                self._window.set_paused_ui(True)
        else:
            self._worker.resume()
            self.set_paused(False)
            if hasattr(self._window, 'set_paused_ui'):
                self._window.set_paused_ui(False)

    def set_paused(self, paused: bool):
        """仅更新托盘菜单的暂停/恢复文案（由主窗口 UI 统一驱动）。"""
        self._pause_action.setText('恢复' if paused else '暂停')

    def on_status(self, data: dict):
        """接收 worker 状态推送，保持托盘菜单与主窗口一致。"""
        if 'paused' in data:
            self.set_paused(bool(data['paused']))

    def _quit(self):
        self._worker.stop()
        QCoreApplication.quit()
