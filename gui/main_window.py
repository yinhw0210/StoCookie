from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QGroupBox, QTabWidget,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QTextCursor


class MainWindow(QMainWindow):
    def __init__(self, worker):
        super().__init__()
        self._worker = worker
        self.setWindowTitle('StoCookie')
        self.setMinimumSize(560, 640)
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)

        # 状态面板
        status_group = QGroupBox('状态')
        status_layout = QVBoxLayout(status_group)

        self._lbl_login = QLabel('登录状态：--')
        self._lbl_sync = QLabel('最近同步：--')
        self._lbl_heartbeat = QLabel('心跳状态：--')
        self._lbl_next_collect = QLabel('下次同步：--')
        self._lbl_next_heartbeat = QLabel('下次心跳：--')

        for lbl in (self._lbl_login, self._lbl_sync, self._lbl_heartbeat,
                    self._lbl_next_collect, self._lbl_next_heartbeat):
            status_layout.addWidget(lbl)

        layout.addWidget(status_group)

        # Cookie 状态一览
        self._lbl_cookie_status = QLabel('Cookie: --')
        self._lbl_cookie_status.setWordWrap(True)
        layout.addWidget(self._lbl_cookie_status)

        # 按钮行 1
        btn_layout1 = QHBoxLayout()
        self._btn_sync = QPushButton('立即同步')
        self._btn_login = QPushButton('重新登录')
        self._btn_pause = QPushButton('暂停')
        self._btn_settings = QPushButton('设置')
        btn_layout1.addWidget(self._btn_sync)
        btn_layout1.addWidget(self._btn_login)
        btn_layout1.addWidget(self._btn_pause)
        btn_layout1.addWidget(self._btn_settings)
        layout.addLayout(btn_layout1)

        # 按钮行 2
        btn_layout2 = QHBoxLayout()
        self._btn_export = QPushButton('导出日志')
        btn_layout2.addWidget(self._btn_export)
        btn_layout2.addStretch()
        layout.addLayout(btn_layout2)

        # 分类日志 Tab
        self._tab_widget = QTabWidget()
        self._log_views = {}
        log_font = QFont('Consolas', 9)

        for tab_name in ('全部', '登录', '上报', '心跳', '错误'):
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setFont(log_font)
            self._tab_widget.addTab(text_edit, tab_name)
            self._log_views[tab_name] = text_edit

        layout.addWidget(self._tab_widget)

    def _connect_signals(self):
        self._btn_sync.clicked.connect(self._on_sync)
        self._btn_login.clicked.connect(self._on_login)
        self._btn_pause.clicked.connect(self._on_pause)
        self._btn_settings.clicked.connect(self._on_settings)
        self._btn_export.clicked.connect(self._on_export)
        self._worker.signals.log_message.connect(self._on_log)
        self._worker.signals.status_update.connect(self._on_status)

    def _on_sync(self):
        self._worker.trigger_sync()

    def _on_login(self):
        self._worker.trigger_login()

    def _on_pause(self):
        if self._btn_pause.text() == '暂停':
            self._worker.pause()
            self._btn_pause.setText('恢复')
        else:
            self._worker.resume()
            self._btn_pause.setText('暂停')

    def _on_settings(self):
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(
            self._worker.collect_interval,
            self._worker.heartbeat_interval,
            self._worker,
            parent=self,
        )
        dlg.exec()

    def _on_export(self):
        from PySide6.QtWidgets import QFileDialog
        import os
        from config import LOG_DIR

        os.startfile(LOG_DIR) if os.name == 'nt' else os.system(f'open "{LOG_DIR}"')

    @Slot(str, str)
    def _on_log(self, msg: str, category: str):
        # 全部 Tab 始终追加
        self._append_log('全部', msg)

        # 对应分类 Tab
        category_map = {
            'login': '登录',
            'report': '上报',
            'heartbeat': '心跳',
        }
        if category in category_map:
            self._append_log(category_map[category], msg)

        # 错误 Tab：包含失败/异常/过期关键词
        error_keywords = ('失败', '异常', '过期', '超时', '错误', 'ERROR', 'WARNING', '✗')
        if any(kw in msg for kw in error_keywords):
            self._append_log('错误', msg)

    def _append_log(self, tab_name: str, msg: str):
        view = self._log_views.get(tab_name)
        if view:
            view.append(msg)
            view.moveCursor(QTextCursor.MoveOperation.End)

    @Slot(dict)
    def _on_status(self, data: dict):
        if 'login' in data:
            self._lbl_login.setText(f'登录状态：{data["login"]}')
        if 'sync' in data:
            self._lbl_sync.setText(f'最近同步：{data["sync"]}')
        if 'heartbeat' in data:
            self._lbl_heartbeat.setText(f'心跳状态：{data["heartbeat"]}')
        if 'next_collect' in data:
            h, rem = divmod(data['next_collect'], 3600)
            m, s = divmod(rem, 60)
            self._lbl_next_collect.setText(f'下次同步：{h:02d}:{m:02d}:{s:02d}')
        if 'next_heartbeat' in data:
            h, rem = divmod(data['next_heartbeat'], 3600)
            m, s = divmod(rem, 60)
            self._lbl_next_heartbeat.setText(f'下次心跳：{h:02d}:{m:02d}:{s:02d}')
        if 'cookie_status' in data:
            parts = []
            for domain, has_cookie in data['cookie_status'].items():
                mark = '✓' if has_cookie else '✗'
                parts.append(f'{domain} {mark}')
            self._lbl_cookie_status.setText(f'Cookie: {" | ".join(parts)}')
        if 'paused' in data and data['paused']:
            self._lbl_next_collect.setText('下次同步：⏸ 已暂停')
            self._lbl_next_heartbeat.setText('下次心跳：⏸ 已暂停')

    def closeEvent(self, event):
        event.ignore()
        self.hide()
