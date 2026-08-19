"""上报成功率趋势图：纯 QPainter 自绘，零外部依赖。

展示最近 N 个采集周期的「正式 / 测试」双环境上报成功率折线，
鼠标悬浮可查看每个周期两条线的具体数值，并标记测试环境上报失败。

背景：STO 的 Cookie 同时上报到两个域名 —— slinghang(正式) 与 lysto(测试)。
lysto 是测试环境，经常发布导致上报失败；双线可一眼区分两个环境是否健康。
"""
from PySide6.QtWidgets import QFrame, QWidget, QVBoxLayout, QLabel, QHBoxLayout, QSizePolicy, QToolTip
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont,
)


class TrendWidget(QFrame):
    MAX_POINTS = 40
    PAD_L, PAD_R, PAD_T, PAD_B = 8, 8, 26, 18

    # 双线配色（申通橙主题下克制使用）
    COLOR_PROD = QColor('#ff9442')   # 正式环境
    COLOR_TEST = QColor('#d29922')   # 测试环境
    COLOR_GRID = QColor(255, 255, 255, 13)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('trendWidget')
        self._rates: list[int] = []          # 总体成功率（KPI 参考）
        self._prod_rates: list[int] = []     # 正式环境成功率
        self._test_rates: list[int] = []     # 测试环境成功率
        self._relogins = 0
        self._hover_idx = None
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

        # 图例
        legend = QWidget()
        legend_layout = QHBoxLayout(legend)
        legend_layout.setContentsMargins(0, 0, 0, 0)
        legend_layout.setSpacing(8)
        leg_prod = QLabel('● 正式')
        leg_prod.setStyleSheet('color:#ff9442;font-size:10px;font-weight:600;')
        leg_test = QLabel('● 测试')
        leg_test.setStyleSheet('color:#d29922;font-size:10px;font-weight:600;')
        legend_layout.addWidget(leg_prod)
        legend_layout.addWidget(leg_test)

        head.addWidget(title)
        head.addStretch()
        head.addWidget(self._stat)
        head.addWidget(legend)
        outer.addLayout(head)
        self._canvas = _Canvas(self)
        outer.addWidget(self._canvas, stretch=1)

    def add_rate(self, rate: int, prod_rate: int = None, test_rate: int = None):
        rate = max(0, min(100, int(rate)))
        self._rates.append(rate)
        # 环境成功率缺省用总体值兜底（单域名上报的两组会是同一数字）
        self._prod_rates.append(int(prod_rate) if prod_rate is not None else rate)
        self._test_rates.append(int(test_rate) if test_rate is not None else rate)
        if len(self._rates) > self.MAX_POINTS:
            self._rates.pop(0)
            self._prod_rates.pop(0)
            self._test_rates.pop(0)
        self._canvas.update()

    def bump_relogin(self):
        self._relogins += 1
        self._stat.setText(f'重登 {self._relogins} 次')
        self._stat.setStyleSheet('color:#d29922;font-size:11px;font-weight:600;')

    def set_last_rate(self, rate: int):
        self._rates[-1] = max(0, min(100, int(rate)))
        self._canvas.update()


class _Canvas(QFrame):
    """真正的绘制区，承载 paintEvent。"""

    def __init__(self, owner: TrendWidget):
        super().__init__(owner)
        self._owner = owner
        self.setObjectName('trendCanvas')
        self.setStyleSheet('background-color:#14161a;border-radius:8px;')
        self.setMinimumHeight(96)
        self.setMouseTracking(True)

    def _x_at(self, i, n, plot_w):
        step = plot_w / max(1, TrendWidget.MAX_POINTS - 1)
        offset = TrendWidget.MAX_POINTS - n
        return TrendWidget.PAD_L + (offset + i) * step

    def _y_at(self, v, plot_h):
        return TrendWidget.PAD_T + plot_h * (1 - v / 100)

    def _draw_line(self, painter, series, n, plot_w, plot_h, color):
        pen = QPen(color)
        pen.setWidth(2)
        painter.setPen(pen)
        x_prev = self._x_at(0, n, plot_w)
        y_prev = self._y_at(series[0], plot_h)
        for i in range(1, n):
            x = self._x_at(i, n, plot_w)
            y = self._y_at(series[i], plot_h)
            painter.drawLine(x_prev, y_prev, x, y)
            x_prev, y_prev = x, y
        # 末端高亮点
        last_x = self._x_at(n - 1, n, plot_w)
        last_y = self._y_at(series[-1], plot_h)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(last_x - 3, last_y - 3, 6, 6)
        # 末端数值
        painter.setPen(QColor('#e6e7ea'))
        painter.drawText(
            max(TrendWidget.PAD_L, min(last_x - 26, self.width() - TrendWidget.PAD_R - 30)),
            max(TrendWidget.PAD_T + 10, last_y - 8),
            f'{series[-1]}%',
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        prod = self._owner._prod_rates
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        pad_l, pad_r, pad_t, pad_b = TrendWidget.PAD_L, TrendWidget.PAD_R, 6, 6
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b

        # 网格线（25/50/75/100%）
        painter.setFont(QFont('JetBrains Mono', 9))
        painter.setPen(TrendWidget.COLOR_GRID)
        for pct in (0, 25, 50, 75, 100):
            y = pad_t + plot_h * (1 - pct / 100)
            painter.drawLine(pad_l, y, w - pad_r, y)

        if not prod:
            painter.setPen(QColor('#686d76'))
            painter.drawText(self.rect(), Qt.AlignCenter, '等待首个采集周期…')
            return

        n = len(prod)
        self._draw_line(painter, prod, n, plot_w, plot_h, TrendWidget.COLOR_PROD)
        self._draw_line(painter, self._owner._test_rates, n, plot_w, plot_h, TrendWidget.COLOR_TEST)

        # 悬浮竖线
        idx = self._owner._hover_idx
        if idx is not None and 0 <= idx < n:
            hx = self._x_at(idx, n, plot_w)
            pen = QPen(QColor(255, 255, 255, 70))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawLine(hx, pad_t, hx, pad_t + plot_h)
            for series, color in ((prod, TrendWidget.COLOR_PROD), (self._owner._test_rates, TrendWidget.COLOR_TEST)):
                cx = self._x_at(idx, n, plot_w)
                cy = self._y_at(series[idx], plot_h)
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(QColor('#14161a'), 2))
                painter.drawEllipse(cx - 4, cy - 4, 8, 8)

    def mouseMoveEvent(self, event):
        prod = self._owner._prod_rates
        if not prod:
            return
        w = self.width()
        pad_l, pad_r = TrendWidget.PAD_L, TrendWidget.PAD_R
        plot_w = w - pad_l - pad_r
        step = plot_w / max(1, TrendWidget.MAX_POINTS - 1)
        offset = TrendWidget.MAX_POINTS - len(prod)
        x = event.position().x()
        idx = round((x - pad_l) / step - offset)
        idx = max(0, min(len(prod) - 1, idx))
        self._owner._hover_idx = idx
        self.update()

        prod_v = prod[idx]
        test_v = self._owner._test_rates[idx]
        text = f'第 {idx + 1} 个周期\n正式: {prod_v}%\n测试: {test_v}%'
        if test_v < 100:
            text += '\n⚠ 测试环境上报失败'
        if self._owner._relogins:
            text += f'\n重登: {self._owner._relogins} 次'
        QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def leaveEvent(self, event):
        self._owner._hover_idx = None
        self.update()
        QToolTip.hideText()
