"""StoCookie 仪表盘复用展示组件。

这些组件只负责"长什么样、怎么更新"，不含任何业务逻辑，
状态数据全部由 main_window 通过信号驱动写入。
"""
from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

# 状态色板（与 styles.py 保持一致）
COLOR_OK = '#10b981'
COLOR_FAIL = '#ef4444'
COLOR_PARTIAL = '#f59e0b'
COLOR_PENDING = '#4b5563'
COLOR_BLUE = '#60a5fa'
COLOR_TEXT = '#e6edf3'
COLOR_MUTED = '#5b6678'


class SectionTitle(QWidget):
    """区块标题：左侧强调竖条 + 标题文字。"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName('sectionTitle')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)
        bar = QFrame()
        bar.setObjectName('sectionBar')
        title = QLabel(text)
        title.setObjectName('sectionTitleText')
        layout.addWidget(bar)
        layout.addWidget(title)
        layout.addStretch()


class MetricCard(QFrame):
    """KPI 指标卡：标签 + 大号数值 + 副说明。"""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName('metricCard')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        self._label = QLabel(label)
        self._label.setObjectName('metricLabel')
        self._value = QLabel('--')
        self._value.setObjectName('metricValue')
        self._sub = QLabel('')
        self._sub.setObjectName('metricSub')
        layout.addWidget(self._label)
        layout.addWidget(self._value)
        layout.addWidget(self._sub)

    def set_value(self, text: str, color: str = COLOR_TEXT, sub: str = ''):
        self._value.setText(text)
        self._value.setStyleSheet(f'color:{color};font-size:22px;font-weight:700;')
        self._sub.setText(sub)
        self._sub.setStyleSheet(f'color:{COLOR_MUTED};font-size:10px;')


class StatePill(QFrame):
    """运行状态药丸：运行中 / 已暂停 / 重登中 / 异常，自带配色。"""

    _STYLES = {
        'running': (COLOR_OK, '#06281f', '运行中'),
        'paused': (COLOR_PARTIAL, '#2a1f06', '已暂停'),
        'maintaining': (COLOR_BLUE, '#0a1d3a', '重登中'),
        'error': (COLOR_FAIL, '#2a0a0a', '登录异常'),
        'starting': ('#8892b0', '#1b2740', '启动中'),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('statePill')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(6)
        self._dot = QFrame()
        self._dot.setObjectName('pillDot')
        self._dot.setFixedSize(8, 8)
        self._text = QLabel('启动中')
        self._text.setObjectName('pillText')
        layout.addWidget(self._dot)
        layout.addWidget(self._text)

    def set_state(self, kind: str, text: str = None):
        color, bg, default = self._STYLES.get(kind, ('#8892b0', '#1b2740', '未知'))
        self.setStyleSheet(f'background-color:{bg};border:1px solid {color};border-radius:14px;')
        self._dot.setStyleSheet(f'background-color:{color};border-radius:4px;')
        self._text.setText(text or default)
        self._text.setStyleSheet(f'color:{color};font-weight:600;font-size:12px;')


class AccountChip(QFrame):
    """当前登录账号芯片。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('accountChip')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 12, 4)
        layout.setSpacing(6)
        dot = QFrame()
        dot.setObjectName('accountDot')
        self._text = QLabel('未登录')
        self._text.setObjectName('accountText')
        layout.addWidget(dot)
        layout.addWidget(self._text)

    def set_account(self, name: str):
        self._text.setText(f'账号：{name}' if name else '未登录')


class ReportRow(QFrame):
    """单行上报项：状态圆点 + 名称 + 最后更新时间，悬停看详情。"""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._name = name
        self.setObjectName('reportRow')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)
        self._dot = QFrame()
        self._dot.setObjectName('reportDot')
        self._dot.setFixedSize(9, 9)
        self._dot.setStyleSheet(f'background-color:{COLOR_PENDING};border-radius:4px;')
        self._name_label = QLabel(name)
        self._name_label.setObjectName('reportRowName')
        self._name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._time = QLabel('')
        self._time.setObjectName('reportRowTime')
        layout.addWidget(self._dot)
        layout.addWidget(self._name_label)
        layout.addWidget(self._time)
        self._status_text = '待采集'

    def set_status(self, ok: bool = False, partial: bool = False, error: str = '', time_str: str = ''):
        self._time.setText(time_str)
        if error == '未采集到':
            color, self._status_text = COLOR_PENDING, '未采集到'
        elif ok:
            color, self._status_text = COLOR_OK, '成功'
        elif partial:
            color, self._status_text = COLOR_PARTIAL, '部分成功'
        else:
            color, self._status_text = COLOR_FAIL, (error or '失败')
        self._dot.setStyleSheet(f'background-color:{color};border-radius:4px;')
        self.setToolTip(f'{self._name}\n状态：{self._status_text}\n更新：{time_str or "—"}')


class ReportGroup(QFrame):
    """上报明细分组：标题 + 若干 ReportRow。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName('reportGroup')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        head = QLabel(title)
        head.setObjectName('reportGroupTitle')
        layout.addWidget(head)
        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(4)
        layout.addLayout(self._body)
        self._rows: dict[str, ReportRow] = {}

    def set_rows(self, labels: list[str]):
        for lbl in labels:
            row = ReportRow(lbl)
            self._body.addWidget(row)
            self._rows[lbl] = row

    def update_item(self, label: str, **kw):
        row = self._rows.get(label)
        if row is None:
            row = ReportRow(label)
            self._body.addWidget(row)
            self._rows[label] = row
        row.set_status(**kw)
