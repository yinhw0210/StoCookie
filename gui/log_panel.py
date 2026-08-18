"""结构化日志面板：级别过滤 + 关键词搜索 + 彩色行 + 环形缓冲。

替代原先的多 Tab QTextEdit，解决长时间运行后卡顿、无过滤、无搜索的问题。
"""
import html as _html

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QPlainTextEdit,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont

_LEVELS = ('全部', '信息', '成功', '警告', '错误')
_LEVEL_COLOR = {
    '成功': '#10b981',
    '警告': '#f59e0b',
    '错误': '#ef4444',
    '信息': '#c9d1d9',
}
# 关键词 -> 级别（命中即归类，优先级 错误 > 警告 > 成功 > 信息）
_ERR_KW = ('失败', '异常', '过期', '超时', '错误', 'ERROR', '✗')
_WARN_KW = ('WARNING', '⚠', '跳过', '未变化', '未采集到')
_OK_KW = ('成功', '✓', '正常', '完成', '已登录')


def _classify(msg: str) -> str:
    if any(kw in msg for kw in _ERR_KW):
        return '错误'
    if any(kw in msg for kw in _WARN_KW):
        return '警告'
    if any(kw in msg for kw in _OK_KW):
        return '成功'
    return '信息'


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('logPanel')
        self._entries = []          # (原始文本, 级别)
        self._max = 2000
        self._filter = '全部'
        self._search = ''
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._chips = {}
        for name in _LEVELS:
            btn = QPushButton(name)
            btn.setObjectName('logChip')
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, n=name: self._set_filter(n))
            bar.addWidget(btn)
            self._chips[name] = btn
        self._chips['全部'].setChecked(True)

        bar.addStretch()
        self._search_edit = QLineEdit()
        self._search_edit.setObjectName('logSearch')
        self._search_edit.setPlaceholderText('搜索日志…')
        self._search_edit.setFixedWidth(180)
        self._search_edit.textChanged.connect(self._on_search)
        bar.addWidget(self._search_edit)
        layout.addLayout(bar)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setObjectName('logView')
        self._view.setMaximumBlockCount(self._max)
        mono = QFont('JetBrains Mono', 11)
        mono.setStyleHint(QFont.Monospace)
        self._view.setFont(mono)
        layout.addWidget(self._view, stretch=1)

    def _set_filter(self, name: str):
        if name == self._filter:
            return
        self._filter = name
        for n, btn in self._chips.items():
            btn.setChecked(n == name)
        self._rebuild()

    def _on_search(self, text: str):
        self._search = text.strip().lower()
        self._rebuild()

    def _pass(self, msg: str, level: str) -> bool:
        if self._filter != '全部' and level != self._filter:
            return False
        if self._search and self._search not in msg.lower():
            return False
        return True

    def _append(self, msg: str, level: str):
        color = _LEVEL_COLOR.get(level, '#c9d1d9')
        self._view.appendHtml(
            f'<span style="color:{color};white-space:pre-wrap">{_html.escape(msg)}</span>'
        )

    def _rebuild(self):
        self._view.clear()
        for msg, level in self._entries:
            if self._pass(msg, level):
                self._append(msg, level)

    @Slot(str, str)
    def add(self, msg: str, category: str = 'general'):
        level = _classify(msg)
        self._entries.append((msg, level))
        if len(self._entries) > self._max:
            self._entries.pop(0)
        if self._pass(msg, level):
            self._append(msg, level)
