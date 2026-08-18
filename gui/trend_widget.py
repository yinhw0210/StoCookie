"""上报成功率趋势图：纯 QPainter 自绘，零外部依赖。

展示最近 N 个采集周期的"上报成功率"面积折线，并在右上角统计重登次数，
帮助运维一眼看出登录态是否稳定（成功率持续 100% 即健康，
频繁掉到低位 = 会话经常被踢、需要排查）。
"""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QHBoxLayout, QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont,
)


class TrendWidget(QFrame):
    MAX_POINTS = 40
    PAD_L, PAD_R, PAD_T, PAD_B = 8, 8, 26, 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('trendWidget')
        self._rates: list[int] = []
        self._relogins = 0
        self._last_rate = None
        self.setMinimumHeight(150)
        sp = self.sizePolicy()
        sp.setVerticalPolicy(QSizePolicy.Preferred)
        self.setSizePolicy(sp)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel('上报成功率趋势')
        title.setObjectName('sectionTitleText')
        self._stat = QLabel('重登 0 次')
        self._stat.setObjectName('trendStat')
        self._stat.setAlignment(Qt.AlignRight)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self._stat)
        outer.addLayout(head)
        self._canvas = _Canvas(self)
        outer.addWidget(self._canvas, stretch=1)

    def add_rate(self, rate: int):
        rate = max(0, min(100, int(rate)))
        self._rates.append(rate)
        self._last_rate = rate
        if len(self._rates) > self.MAX_POINTS:
            self._rates.pop(0)
        self._canvas.update()

    def bump_relogin(self):
        self._relogins += 1
        self._stat.setText(f'重登 {self._relogins} 次')
        self._stat.setStyleSheet('color:#f59e0b;font-size:11px;font-weight:600;')

    def set_last_rate(self, rate: int):
        self._last_rate = max(0, min(100, int(rate)))
        self._canvas.update()


class _Canvas(QFrame):
    """真正的绘制区，承载 paintEvent。"""

    def __init__(self, owner: TrendWidget):
        super().__init__(owner)
        self._owner = owner
        self.setObjectName('trendCanvas')
        self.setStyleSheet('background-color:#0f1420;border-radius:8px;')
        self.setMinimumHeight(96)

    def paintEvent(self, event):
        super().paintEvent(event)
        rates = self._owner._rates
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        pad_l, pad_r, pad_t, pad_b = TrendWidget.PAD_L, TrendWidget.PAD_R, 6, 6
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b

        # 网格线（25/50/75/100%）
        grid = QPen(QColor('#243049'))
        grid.setWidth(1)
        painter.setPen(grid)
        font = QFont('JetBrains Mono', 9)
        painter.setFont(font)
        painter.setPen(QColor('#3a4a66'))
        for pct in (0, 25, 50, 75, 100):
            y = pad_t + plot_h * (1 - pct / 100)
            painter.drawLine(pad_l, y, w - pad_r, y)

        if not rates:
            painter.setPen(QColor('#5b6678'))
            painter.drawText(self.rect(), Qt.AlignCenter, '等待首个采集周期…')
            return

        n = len(rates)
        step = plot_w / max(1, TrendWidget.MAX_POINTS - 1)
        # 仅绘制最近 MAX_POINTS 个点，左移铺满
        offset = TrendWidget.MAX_POINTS - n
        x_at = lambda i: pad_l + (offset + i) * step
        y_at = lambda v: pad_t + plot_h * (1 - v / 100)

        path = QPainterPath()
        path.moveTo(x_at(0), y_at(rates[0]))
        for i in range(1, n):
            path.lineTo(x_at(i), y_at(rates[i]))

        # 面积填充
        area = QPainterPath(path)
        area.lineTo(x_at(n - 1), pad_t + plot_h)
        area.lineTo(x_at(0), pad_t + plot_h)
        area.closeSubpath()
        grad = QLinearGradient(0, pad_t, 0, pad_t + plot_h)
        grad.setColorAt(0, QColor(67, 97, 238, 120))
        grad.setColorAt(1, QColor(67, 97, 238, 8))
        painter.fillPath(area, QBrush(grad))

        # 折线
        line_pen = QPen(QColor('#60a5fa'))
        line_pen.setWidth(2)
        painter.setPen(line_pen)
        painter.drawPath(path)

        # 末端高亮点 + 数值
        last_x = x_at(n - 1)
        last_y = y_at(rates[-1])
        painter.setBrush(QBrush(QColor('#60a5fa')))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(last_x - 3, last_y - 3, 6, 6)
        painter.setPen(QColor('#cbd5e1'))
        painter.drawText(
            max(pad_l, min(last_x - 26, w - pad_r - 30)),
            max(pad_t + 10, last_y - 8),
            f'{rates[-1]}%',
        )
