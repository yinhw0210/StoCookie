import os
import platform

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QFrame, QTabWidget,
    QGridLayout, QSizePolicy,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QTextCursor

from gui.styles import DARK_THEME


class _StatusCard(QFrame):
    def __init__(self, label_text: str):
        super().__init__()
        self.setObjectName('statusCard')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        self._label = QLabel(label_text)
        self._label.setObjectName('statusLabel')
        self._label.setAlignment(Qt.AlignCenter)

        self._value = QLabel('--')
        self._value.setObjectName('statusValue')
        self._value.setAlignment(Qt.AlignCenter)

        layout.addWidget(self._label)
        layout.addWidget(self._value)

    def set_value(self, text: str, color: str = '#e0e0e0'):
        self._value.setText(text)
        self._value.setStyleSheet(f'color: {color}; font-size: 14px; font-weight: 600;')


class _ReportItem(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName('reportItem')
        self.setFixedHeight(24)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        self._dot = QFrame()
        self._dot.setObjectName('dotPending')
        self._dot.setFixedSize(8, 8)

        self._name = QLabel('--')
        self._name.setObjectName('reportItemName')
        self._name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._time = QLabel('')
        self._time.setObjectName('reportItemTime')

        layout.addWidget(self._dot)
        layout.addWidget(self._name)
        layout.addWidget(self._time)

    def update_status(self, name: str, ok: bool = False, partial: bool = False, error: str = '', time_str: str = ''):
        self._name.setText(name)
        self._time.setText(time_str)
        if error == '未采集到':
            self._dot.setObjectName('dotPending')
        elif ok:
            self._dot.setObjectName('dotOk')
        elif partial:
            self._dot.setObjectName('dotPartial')
        else:
            self._dot.setObjectName('dotFail')
        self._dot.setStyle(self._dot.style())


class MainWindow(QMainWindow):
    def __init__(self, worker):
        super().__init__()
        self._worker = worker
        self.setWindowTitle('StoCookie')
        self.setMinimumSize(580, 660)
        self.setStyleSheet(DARK_THEME)
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        central = QWidget()
        central.setObjectName('centralWidget')
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 标题栏
        header = QFrame()
        header.setObjectName('headerFrame')
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)

        title = QLabel('StoCookie')
        title.setObjectName('appTitle')
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._btn_sync = QPushButton('立即同步')
        self._btn_sync.setObjectName('btnSync')
        self._btn_login = QPushButton('重新登录')
        self._btn_login.setObjectName('btnLogin')
        self._btn_pause = QPushButton('暂停')
        self._btn_pause.setObjectName('btnPause')
        self._btn_settings = QPushButton('设置')
        self._btn_settings.setObjectName('btnSettings')

        for btn in (self._btn_sync, self._btn_login, self._btn_pause, self._btn_settings):
            header_layout.addWidget(btn)

        layout.addWidget(header)

        # 状态卡片行
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._card_login = _StatusCard('登录状态')
        self._card_countdown = _StatusCard('下次同步')
        self._card_heartbeat = _StatusCard('心跳状态')
        status_row.addWidget(self._card_login)
        status_row.addWidget(self._card_countdown)
        status_row.addWidget(self._card_heartbeat)
        layout.addLayout(status_row)

        # 上报状态区
        report_frame = QFrame()
        report_frame.setObjectName('reportFrame')
        report_layout = QVBoxLayout(report_frame)
        report_layout.setContentsMargins(10, 8, 10, 8)
        report_layout.setSpacing(6)

        report_header = QHBoxLayout()
        self._lbl_report_title = QLabel('上报状态')
        self._lbl_report_title.setObjectName('reportTitle')
        self._lbl_report_summary = QLabel('')
        self._lbl_report_summary.setObjectName('reportSummary')
        report_header.addWidget(self._lbl_report_title)
        report_header.addStretch()
        report_header.addWidget(self._lbl_report_summary)
        report_layout.addLayout(report_header)

        self._report_grid = QGridLayout()
        self._report_grid.setSpacing(4)
        self._report_items: dict[str, _ReportItem] = {}
        report_layout.addLayout(self._report_grid)

        layout.addWidget(report_frame)

        # 日志 Tab
        self._tab_widget = QTabWidget()
        self._log_views = {}
        log_font = QFont('JetBrains Mono', 11)
        log_font.setStyleHint(QFont.Monospace)

        for tab_name in ('全部', '登录', '上报', '心跳', 'PDD', '错误'):
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setFont(log_font)
            self._tab_widget.addTab(text_edit, tab_name)
            self._log_views[tab_name] = text_edit

        layout.addWidget(self._tab_widget, stretch=1)

    def _connect_signals(self):
        self._btn_sync.clicked.connect(self._worker.trigger_sync)
        self._btn_login.clicked.connect(self._worker.trigger_login)
        self._btn_pause.clicked.connect(self._toggle_pause)
        self._btn_settings.clicked.connect(self._open_settings)
        self._worker.signals.log_message.connect(self._on_log)
        self._worker.signals.status_update.connect(self._on_status)

    def _toggle_pause(self):
        if self._worker.is_paused:
            self._worker.resume()
            self._btn_pause.setText('暂停')
        else:
            self._worker.pause()
            self._btn_pause.setText('恢复')

    def _open_settings(self):
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(
            self._worker.collect_interval,
            self._worker.heartbeat_interval,
            self._worker,
            parent=self,
        )
        dlg.exec()

    def _ensure_report_item(self, label: str) -> _ReportItem:
        if label not in self._report_items:
            item = _ReportItem()
            idx = len(self._report_items)
            row = idx // 2
            col = idx % 2
            self._report_grid.addWidget(item, row, col)
            self._report_items[label] = item
        return self._report_items[label]

    @Slot(str, str)
    def _on_log(self, msg: str, category: str):
        self._log_views['全部'].append(msg)
        self._auto_scroll(self._log_views['全部'])

        tab_map = {'login': '登录', 'report': '上报', 'heartbeat': '心跳', 'pdd': 'PDD'}
        if category in tab_map:
            view = self._log_views[tab_map[category]]
            view.append(msg)
            self._auto_scroll(view)

        error_keywords = ('失败', '异常', '过期', '超时', '错误', 'ERROR', 'WARNING', '✗', '⚠')
        if any(kw in msg for kw in error_keywords):
            self._log_views['错误'].append(msg)
            self._auto_scroll(self._log_views['错误'])

    def _auto_scroll(self, text_edit: QTextEdit):
        cursor = text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        text_edit.setTextCursor(cursor)

    @Slot(dict)
    def _on_status(self, data: dict):
        if 'login' in data:
            text = data['login']
            color = '#10b981' if '成功' in text or '已登录' in text or '启动' not in text and '失败' not in text else '#f59e0b'
            if '失败' in text:
                color = '#ef4444'
            self._card_login.set_value(text, color)

        if 'sync' in data:
            pass  # 汇总信息在 report_status 中展示

        if 'heartbeat' in data:
            text = data['heartbeat']
            color = '#10b981' if '正常' in text else '#f59e0b' if '检测' in text else '#ef4444'
            self._card_heartbeat.set_value(text, color)

        if 'next_collect' in data:
            secs = data['next_collect']
            h, rem = divmod(secs, 3600)
            m, s = divmod(rem, 60)
            self._card_countdown.set_value(f'{h:02d}:{m:02d}:{s:02d}', '#60a5fa')

        if 'paused' in data and data['paused']:
            self._card_countdown.set_value('⏸ 已暂停', '#f59e0b')

        if 'report_status' in data:
            report_status = data['report_status']
            total_ok = 0
            total_partial = 0
            total_fail = 0
            total_missing = 0

            for label, info in report_status.items():
                item = self._ensure_report_item(label)
                time_str = info.get('time', '')
                error = info.get('error', '')
                ok = info.get('ok', False)
                partial = info.get('partial', False)
                item.update_status(label, ok=ok, partial=partial, error=error, time_str=time_str)

                if error == '未采集到':
                    total_missing += 1
                elif ok:
                    total_ok += 1
                elif partial:
                    total_partial += 1
                else:
                    total_fail += 1

            parts = []
            if total_ok: parts.append(f'成功{total_ok}')
            if total_partial: parts.append(f'部分{total_partial}')
            if total_fail: parts.append(f'失败{total_fail}')
            if total_missing: parts.append(f'未采集{total_missing}')
            self._lbl_report_summary.setText(' / '.join(parts))

        if 'pdd_status' in data:
            pdd_status = data['pdd_status']
            for label, info in pdd_status.items():
                item = self._ensure_report_item(f'PDD: {label}')
                time_str = info.get('time', '')
                error = info.get('error', '')
                ok = info.get('ok', False)
                partial = info.get('partial', False)
                item.update_status(f'PDD: {label}', ok=ok, partial=partial, error=error, time_str=time_str)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
