from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QGroupBox,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QTextCursor


class MainWindow(QMainWindow):
    def __init__(self, worker):
        super().__init__()
        self._worker = worker
        self.setWindowTitle('StoCookie')
        self.setMinimumSize(480, 520)
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)

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

        # 按钮
        btn_layout = QHBoxLayout()
        self._btn_sync = QPushButton('立即同步')
        self._btn_login = QPushButton('重新登录')
        btn_layout.addWidget(self._btn_sync)
        btn_layout.addWidget(self._btn_login)
        layout.addLayout(btn_layout)

        # 日志
        log_group = QGroupBox('日志')
        log_layout = QVBoxLayout(log_group)
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont('Consolas', 9))
        log_layout.addWidget(self._log_view)
        layout.addWidget(log_group)

    def _connect_signals(self):
        self._btn_sync.clicked.connect(self._on_sync)
        self._btn_login.clicked.connect(self._on_login)
        self._worker.signals.log_message.connect(self._on_log)
        self._worker.signals.status_update.connect(self._on_status)

    def _on_sync(self):
        self._worker.trigger_sync()

    def _on_login(self):
        self._worker.trigger_login()

    @Slot(str)
    def _on_log(self, msg: str):
        self._log_view.append(msg)
        self._log_view.moveCursor(QTextCursor.MoveOperation.End)

    @Slot(dict)
    def _on_status(self, data: dict):
        if 'login' in data:
            self._lbl_login.setText(f'登录状态：{data["login"]}')
        if 'sync' in data:
            self._lbl_sync.setText(f'最近同步：{data["sync"]}')
        if 'heartbeat' in data:
            self._lbl_heartbeat.setText(f'心跳状态：{data["heartbeat"]}')
        if 'next_collect' in data:
            m, s = divmod(data['next_collect'], 60)
            self._lbl_next_collect.setText(f'下次同步：{m:02d}:{s:02d}')
        if 'next_heartbeat' in data:
            m, s = divmod(data['next_heartbeat'], 60)
            self._lbl_next_heartbeat.setText(f'下次心跳：{m:02d}:{s:02d}')

    def closeEvent(self, event):
        event.ignore()
        self.hide()
