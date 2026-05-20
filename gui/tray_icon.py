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
            self._pause_action.setText('恢复')
        else:
            self._worker.resume()
            self._pause_action.setText('暂停')

    def _quit(self):
        self._worker.stop()
        QCoreApplication.quit()
