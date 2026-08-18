# StoCookie 深色主题。集中管理配色与组件样式，保证整站统一。
# 配色：背景 #0f1420 / 面板 #16213e / 卡片 #1b2740 / 强调蓝 #4361ee / 亮蓝 #60a5fa
#       成功 #10b981 / 警告 #f59e0b / 失败 #ef4444 / 待定 #4b5563
#       主文字 #e6edf3 / 次文字 #8892b0 / 弱文字 #5b6678

DARK_THEME = """
/* ===== 基础 ===== */
QMainWindow { background-color: #0f1420; }
QWidget#centralWidget { background-color: #0f1420; }

* { font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif; }

/* ===== 顶部标题栏 ===== */
QFrame#appHeader {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #16213e, stop:1 #1b2740);
    border-radius: 12px;
    padding: 10px 14px;
}
QLabel#appTitle { color: #ffffff; font-size: 18px; font-weight: 700; }
QLabel#appSubtitle { color: #8892b0; font-size: 11px; }
QFrame#titleDot {
    background-color: #4361ee; border-radius: 6px;
    min-width: 12px; max-width: 12px; min-height: 12px; max-height: 12px;
}

/* 状态药丸 */
QFrame#statePill { border-radius: 14px; }
QLabel#pillText { font-size: 12px; font-weight: 600; }
QFrame#pillDot { border-radius: 4px; }

/* 账号芯片 */
QFrame#accountChip {
    background-color: #1b2740; border: 1px solid #2d3748;
    border-radius: 14px; padding: 4px 12px;
}
QLabel#accountText { color: #cbd5e1; font-size: 12px; }
QFrame#accountDot {
    background-color: #10b981; border-radius: 4px;
    min-width: 7px; max-width: 7px; min-height: 7px; max-height: 7px;
}

/* ===== 按钮 ===== */
QPushButton {
    border: none; border-radius: 8px;
    padding: 8px 16px; font-size: 12px; font-weight: 600;
}
QPushButton#btnSync { background-color: #4361ee; color: #ffffff; }
QPushButton#btnSync:hover { background-color: #3a56d4; }
QPushButton#btnSync:pressed { background-color: #2f48b8; }
QPushButton#btnPrimary { background-color: #4361ee; color: #ffffff; }
QPushButton#btnPrimary:hover { background-color: #3a56d4; }
QPushButton#btnLogin { background-color: #2d3748; color: #e0e0e0; }
QPushButton#btnLogin:hover { background-color: #3d4a5c; }
QPushButton#btnPause { background-color: #f59e0b; color: #1a1a2e; }
QPushButton#btnPause:hover { background-color: #d97706; }
QPushButton#btnSettings { background-color: #2d3748; color: #e0e0e0; }
QPushButton#btnSettings:hover { background-color: #3d4a5c; }
QPushButton#btnGhost {
    background-color: transparent; color: #8892b0;
    border: 1px solid #2d3748;
}
QPushButton#btnGhost:hover { color: #cbd5e1; border-color: #4b5563; }

/* ===== KPI 指标卡 ===== */
QFrame#metricCard {
    background-color: #1b2740; border: 1px solid #243049;
    border-radius: 12px; padding: 12px 14px;
}
QLabel#metricLabel { color: #8892b0; font-size: 11px; }
QLabel#metricValue { font-size: 22px; font-weight: 700; }
QLabel#metricSub { color: #5b6678; font-size: 10px; }

/* ===== 区块标题 ===== */
QWidget#sectionTitle { background: transparent; }
QFrame#sectionBar {
    background-color: #4361ee; border-radius: 2px;
    min-width: 3px; max-width: 3px; min-height: 14px; max-height: 14px;
}
QLabel#sectionTitleText { color: #e6edf3; font-size: 13px; font-weight: 600; }

/* ===== 上报明细分组 ===== */
QFrame#reportGroup {
    background-color: #16213e; border: 1px solid #243049;
    border-radius: 12px; padding: 12px 14px;
}
QLabel#reportGroupTitle {
    color: #60a5fa; font-size: 12px; font-weight: 700;
    padding-bottom: 6px;
}
QFrame#reportRow {
    background-color: #1b2740; border-radius: 8px;
    padding: 5px 10px;
}
QLabel#reportRowName { color: #cbd5e1; font-size: 12px; }
QLabel#reportRowTime { color: #5b6678; font-size: 10px; }

/* ===== 趋势图容器 ===== */
QFrame#trendWidget {
    background-color: #16213e; border: 1px solid #243049;
    border-radius: 12px; padding: 12px 14px;
}
QLabel#trendStat { color: #8892b0; font-size: 11px; }
QLabel#trendBig { font-size: 18px; font-weight: 700; }

/* ===== 日志面板 ===== */
QFrame#logPanel { background-color: #16213e; border: 1px solid #243049; border-radius: 12px; padding: 12px; }
QPushButton#logChip {
    background-color: #1b2740; color: #8892b0;
    border: 1px solid #243049; border-radius: 12px;
    padding: 4px 12px; font-size: 11px; font-weight: 500;
}
QPushButton#logChip:checked {
    background-color: #4361ee; color: #ffffff; border-color: #4361ee;
}
QPushButton#logChip:hover { color: #cbd5e1; }
QLineEdit#logSearch {
    background-color: #1b2740; color: #e6edf3;
    border: 1px solid #243049; border-radius: 8px;
    padding: 5px 10px; font-size: 12px;
}
QLineEdit#logSearch:focus { border-color: #4361ee; }
QPlainTextEdit#logView {
    background-color: #0f1420; color: #94a3b8;
    border: 1px solid #243049; border-radius: 8px;
    font-family: "JetBrains Mono", "Consolas", "Menlo", monospace;
    font-size: 11px; padding: 8px;
}

/* ===== 底部状态条 ===== */
QFrame#statusBar { background-color: #16213e; border-radius: 10px; padding: 6px 12px; }
QLabel#statusText { color: #8892b0; font-size: 11px; }
QFrame#connDot {
    background-color: #10b981; border-radius: 4px;
    min-width: 7px; max-width: 7px; min-height: 7px; max-height: 7px;
}

/* ===== 通用文本 ===== */
QLabel#muted { color: #5b6678; font-size: 11px; }

/* ===== 滚动条 ===== */
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background-color: #16213e; width: 8px; border-radius: 4px; }
QScrollBar::handle:vertical { background-color: #2d3748; border-radius: 4px; min-height: 20px; }
QScrollBar::handle:vertical:hover { background-color: #4b5563; }
QScrollBar:horizontal { background-color: #16213e; height: 8px; border-radius: 4px; }
QScrollBar::handle:horizontal { background-color: #2d3748; border-radius: 4px; min-width: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { height: 0; width: 0; }

/* ===== 日志 Tab(保留兼容) ===== */
QTabWidget::pane { border: none; background-color: #16213e; border-radius: 0 0 10px 10px; }
QTabWidget::tab-bar { alignment: left; }
QTabBar { background-color: #16213e; }
QTabBar::tab {
    background-color: transparent; color: #8892b0;
    padding: 8px 14px; border: none; border-bottom: 2px solid transparent; font-size: 12px;
}
QTabBar::tab:selected { color: #60a5fa; border-bottom: 2px solid #4361ee; }
QTabBar::tab:hover { color: #a0aec0; }

QTextEdit {
    background-color: #0f1420; color: #94a3b8; border: none;
    font-family: "JetBrains Mono", "Consolas", "Menlo", monospace;
    font-size: 11px; padding: 8px;
}

/* ===== 设置弹窗 ===== */
QDialog { background-color: #0f1420; }
QDialog QLabel { color: #e0e0e0; font-size: 12px; }
QDialog QSpinBox, QDialog QLineEdit {
    background-color: #16213e; color: #e0e0e0;
    border: 1px solid #2d3748; border-radius: 4px;
    padding: 4px 8px; font-size: 12px;
}
QDialog QSpinBox:focus, QDialog QLineEdit:focus { border-color: #4361ee; }
QDialog QCheckBox { color: #e0e0e0; font-size: 12px; }
QDialog QCheckBox::indicator {
    width: 14px; height: 14px; border-radius: 3px;
    border: 1px solid #4b5563; background-color: #16213e;
}
QDialog QCheckBox::indicator:checked { background-color: #4361ee; border-color: #4361ee; }
QDialog QPushButton { min-width: 60px; }
"""
