"""StoCookie 主窗口（仪表盘）。

信息架构：
  ┌ 顶部状态栏：标识 + 运行态药丸 + 当前账号 + 操作按钮
  ├ KPI 指标卡：会话健康 / 下次同步 / 下次心跳 / 上报成功率 / 运行时长
  ├ 左：上报明细（申通网点 / 拼多多 / 客户经营分析 分组，逐项状态）
  └ 右：上报成功率趋势图 + 结构化日志（级别过滤 + 搜索）
  └ 底部状态条：最近上报时间 + 连接状态

所有数据来自 worker.signals（log_message / status_update），本窗口只消费、不持有业务状态。
"""
import re
import time

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSplitter, QSizePolicy, QGridLayout,
)
from PySide6.QtCore import Qt, Slot, QTimer

from gui.styles import DARK_THEME
from gui.widgets import (
    SectionTitle, MetricCard, StatePill, AccountChip,
    ReportGroup, ReportRow, COLOR_OK, COLOR_FAIL, COLOR_PARTIAL, COLOR_ACCENT, COLOR_TEXT,
)
from gui.log_panel import LogPanel
from gui.trend_widget import TrendWidget
from cookie_collector import EXPECTED_REPORT_ITEMS
from worker import ZC_STATUS_LABEL


class MainWindow(QMainWindow):
    def __init__(self, worker):
        super().__init__()
        self._worker = worker
        self._tray = None

        # 本地 UI 状态（仅用于展示）
        self._start_time = time.time()
        self._paused = False
        self._maintaining = False
        self._login_error = False
        self._next_collect = 0
        self._next_heartbeat = 0
        self._last_sync_time = ''

        self.setWindowTitle('StoCookie · 申通网点登录态代理')
        self.setMinimumSize(1000, 720)
        self.resize(1120, 820)
        self.setStyleSheet(DARK_THEME)

        self._build_ui()
        self._connect_signals()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    # ----------------------------------------------------------------- UI
    def _build_ui(self):
        central = QWidget()
        central.setObjectName('centralWidget')
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        root.addWidget(self._build_header())
        root.addWidget(self._build_kpi_row())
        root.addWidget(self._build_splitter(), stretch=1)
        root.addWidget(self._build_report_panel())
        root.addWidget(self._build_status_bar())

    def _build_header(self):
        header = QFrame()
        header.setObjectName('appHeader')
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.setSpacing(10)

        title_group = QVBoxLayout()
        title_group.setSpacing(2)
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        dot = QFrame()
        dot.setObjectName('titleDot')
        title = QLabel('StoCookie')
        title.setObjectName('appTitle')
        row1.addWidget(dot)
        row1.addWidget(title)
        row1.addStretch()
        subtitle = QLabel('申通网点登录态代理 · Cookie 保活上报')
        subtitle.setObjectName('appSubtitle')
        title_group.addLayout(row1)
        title_group.addWidget(subtitle)
        hl.addLayout(title_group)

        hl.addStretch()
        self._pill = StatePill()
        self._account_chip = AccountChip()
        hl.addWidget(self._pill)
        hl.addWidget(self._account_chip)
        hl.addSpacing(12)

        self._btn_sync = QPushButton('立即同步')
        self._btn_sync.setObjectName('btnSync')
        self._btn_login = QPushButton('重新登录')
        self._btn_login.setObjectName('btnLogin')
        self._btn_pause = QPushButton('暂停')
        self._btn_pause.setObjectName('btnPause')
        self._btn_settings = QPushButton('设置')
        self._btn_settings.setObjectName('btnSettings')
        for b in (self._btn_sync, self._btn_login, self._btn_pause, self._btn_settings):
            hl.addWidget(b)
        return header

    def _build_kpi_row(self):
        container = QWidget()
        container.setObjectName('kpiRow')
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self._card_health = MetricCard('会话健康')
        self._card_collect = MetricCard('下次同步')
        self._card_heartbeat = MetricCard('下次心跳')
        self._card_rate = MetricCard('上报成功率')
        self._card_uptime = MetricCard('运行时长')
        for c in (self._card_health, self._card_collect, self._card_heartbeat,
                  self._card_rate, self._card_uptime):
            c.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            row.addWidget(c)
        return container

    def _build_splitter(self):
        # 主区：趋势图（上，固定高）+ 结构化日志（下，自适应）
        pane = QWidget()
        pane.setObjectName('mainPane')
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._trend = TrendWidget()
        self._trend.setFixedHeight(160)
        self._log_panel = LogPanel()
        layout.addWidget(self._trend)
        layout.addWidget(self._log_panel, stretch=1)
        return pane

    def _build_report_panel(self):
        # 上报明细（底部，一行两个紧凑网格）：申通 STO 14 项 + PDD + 客户经营
        panel = QWidget()
        panel.setObjectName('reportPanel')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(SectionTitle('上报明细'))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        self._report_rows = {}
        labels = [it['label'] for it in EXPECTED_REPORT_ITEMS]
        labels += ['SUB_PASS_ID (PDD)', ZC_STATUS_LABEL]
        for idx, lbl in enumerate(labels):
            row = ReportRow(lbl)
            self._report_rows[lbl] = row
            r, c = divmod(idx, 2)
            grid.addWidget(row, r, c)
        layout.addLayout(grid)
        panel.setMaximumHeight(320)
        return panel

    def _build_status_bar(self):
        bar = QFrame()
        bar.setObjectName('statusBar')
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(12, 6, 12, 6)
        hl.setSpacing(8)
        conn = QFrame()
        conn.setObjectName('connDot')
        self._status_text = QLabel('正在启动…')
        self._status_text.setObjectName('statusText')
        hl.addWidget(conn)
        hl.addWidget(self._status_text)
        hl.addStretch()
        self._heartbeat_text = QLabel('')
        self._heartbeat_text.setObjectName('statusText')
        hl.addWidget(self._heartbeat_text)
        return bar

    # ----------------------------------------------------------------- 信号
    def _connect_signals(self):
        self._btn_sync.clicked.connect(self._worker.trigger_sync)
        self._btn_login.clicked.connect(self._worker.trigger_login)
        self._btn_pause.clicked.connect(self._toggle_pause)
        self._btn_settings.clicked.connect(self._open_settings)
        self._worker.signals.log_message.connect(self._log_panel.add)
        self._worker.signals.status_update.connect(self._on_status)

    def set_tray(self, tray):
        self._tray = tray

    def _toggle_pause(self):
        if self._worker.is_paused:
            self._worker.resume()
            self.set_paused_ui(False)
        else:
            self._worker.pause()
            self.set_paused_ui(True)

    def set_paused_ui(self, paused: bool):
        """统一的暂停态 UI 驱动（主窗口按钮 / 托盘菜单共用）。"""
        self._paused = paused
        self._btn_pause.setText('恢复' if paused else '暂停')
        if self._tray:
            self._tray.set_paused(paused)
        if paused:
            self._card_collect.set_value('⏸ 已暂停', COLOR_PARTIAL)
            self._card_heartbeat.set_value('⏸ 已暂停', COLOR_PARTIAL)
        else:
            self._update_countdown()
        self._refresh_pill()

    def _open_settings(self):
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(
            self._worker.collect_interval,
            self._worker.heartbeat_interval,
            self._worker,
            parent=self,
        )
        dlg.exec()

    # ----------------------------------------------------------------- 状态
    @Slot(dict)
    def _on_status(self, data: dict):
        if 'account' in data:
            self._account = data['account']
            self._account_chip.set_account(self._account)

        if 'login' in data:
            self._apply_login_text(data['login'])

        if 'paused' in data:
            self.set_paused_ui(bool(data['paused']))

        if 'sync' in data:
            self._apply_sync_text(data['sync'])

        if 'heartbeat' in data:
            self._heartbeat_text.setText(f'心跳：{data["heartbeat"]}')

        if 'next_collect' in data:
            self._next_collect = data['next_collect']
            self._card_collect.set_value(self._fmt(self._next_collect), COLOR_ACCENT)

        if 'next_heartbeat' in data:
            self._next_heartbeat = data['next_heartbeat']
            self._card_heartbeat.set_value(self._fmt(self._next_heartbeat), COLOR_ACCENT)

        if 'report_status' in data:
            self._apply_report_status(data['report_status'])

        if 'pdd_status' in data:
            for label, info in data['pdd_status'].items():
                r = self._report_rows.get(label)
                if r:
                    r.set_status(**self._row_kwargs(info))

        if 'zc_status' in data:
            for label, info in data['zc_status'].items():
                r = self._report_rows.get(label)
                if r:
                    r.set_status(**self._row_kwargs(info))

    def _row_kwargs(self, info: dict) -> dict:
        return {
            'ok': info.get('ok', False),
            'partial': info.get('partial', False),
            'error': info.get('error', ''),
            'time_str': info.get('time', ''),
            'targets': info.get('targets', []),
        }

    def _apply_login_text(self, text: str):
        if '登录中' in text:
            self._maintaining, self._login_error = True, False
        elif '登录失败' in text:
            self._maintaining, self._login_error = False, True
        elif '已登录' in text:
            self._maintaining, self._login_error = False, False
        # '启动中…' 等不重置维护态
        self._refresh_pill()

    def _apply_sync_text(self, text: str):
        m = re.search(r'\((\d{1,2}:\d{2}:\d{2})\)', text)
        if m:
            self._last_sync_time = m.group(1)
        self._status_text.setText(f'最近上报：{self._last_sync_time or "—"}')

    def _apply_report_status(self, report_status: dict):
        total = len(report_status)
        ok = fail = partial = missing = 0
        prod_ok = prod_total = 0
        test_ok = test_total = 0
        for label, info in report_status.items():
            r = self._report_rows.get(label)
            if r:
                r.set_status(**self._row_kwargs(info))
            if info.get('error') == '未采集到':
                missing += 1
            elif info.get('ok'):
                ok += 1
            elif info.get('partial'):
                partial += 1
            else:
                fail += 1
            # 按环境累计正式 / 测试 成功率
            for t in info.get('targets', []):
                if t.get('env') == 'prod':
                    prod_total += 1
                    if t.get('ok'):
                        prod_ok += 1
                elif t.get('env') == 'test':
                    test_total += 1
                    if t.get('ok'):
                        test_ok += 1

        # 会话健康
        if fail > 0:
            self._card_health.set_value('异常', COLOR_FAIL, f'{fail} 项上报失败')
        elif missing > 0:
            self._card_health.set_value('部分缺失', COLOR_PARTIAL, f'{missing} 项未采集')
        else:
            self._card_health.set_value('正常', COLOR_OK, f'{ok}/{total} 项成功')

        # 上报成功率（总体 / 正式环境 / 测试环境）
        rate = round(ok / total * 100) if total else 0
        color = COLOR_OK if rate >= 100 else COLOR_PARTIAL if rate >= 50 else COLOR_FAIL
        self._card_rate.set_value(f'{rate}%', color, f'{ok}/{total} 成功')
        prod_rate = round(prod_ok / prod_total * 100) if prod_total else None
        test_rate = round(test_ok / test_total * 100) if test_total else None
        self._trend.add_rate(rate, prod_rate, test_rate)

    def _refresh_pill(self):
        if self._paused:
            self._pill.set_state('paused')
        elif self._maintaining:
            self._pill.set_state('maintaining')
        elif self._login_error:
            self._pill.set_state('error')
        else:
            self._pill.set_state('running')

    # ----------------------------------------------------------------- 计时
    def _tick(self):
        if not self._paused:
            if self._next_collect > 0:
                self._next_collect = max(0, self._next_collect - 1)
            if self._next_heartbeat > 0:
                self._next_heartbeat = max(0, self._next_heartbeat - 1)
            self._update_countdown()
        elapsed = int(time.time() - self._start_time)
        self._card_uptime.set_value(self._fmt(elapsed), COLOR_TEXT)

    def _update_countdown(self):
        self._card_collect.set_value(self._fmt(self._next_collect), COLOR_ACCENT)
        self._card_heartbeat.set_value(self._fmt(self._next_heartbeat), COLOR_ACCENT)

    @staticmethod
    def _fmt(secs: int) -> str:
        secs = max(0, int(secs))
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f'{h:02d}:{m:02d}:{s:02d}'

    def closeEvent(self, event):
        event.ignore()
        self.hide()
