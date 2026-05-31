DARK_THEME = """
QMainWindow {
    background-color: #1a1a2e;
}

QWidget#centralWidget {
    background-color: #1a1a2e;
}

/* 标题栏 */
QFrame#headerFrame {
    background-color: #16213e;
    border-radius: 10px;
    padding: 8px 12px;
}

QLabel#appTitle {
    color: #ffffff;
    font-size: 16px;
    font-weight: bold;
}

/* 按钮通用 */
QPushButton {
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
}

QPushButton#btnSync {
    background-color: #4361ee;
    color: #ffffff;
}
QPushButton#btnSync:hover { background-color: #3a56d4; }
QPushButton#btnSync:pressed { background-color: #2f48b8; }

QPushButton#btnLogin {
    background-color: #2d3748;
    color: #e0e0e0;
}
QPushButton#btnLogin:hover { background-color: #3d4a5c; }

QPushButton#btnPause {
    background-color: #f59e0b;
    color: #1a1a2e;
}
QPushButton#btnPause:hover { background-color: #d97706; }

QPushButton#btnSettings {
    background-color: #2d3748;
    color: #e0e0e0;
}
QPushButton#btnSettings:hover { background-color: #3d4a5c; }

/* 状态卡片 */
QFrame#statusCard {
    background-color: #16213e;
    border-radius: 8px;
    padding: 8px 12px;
}

QLabel#statusLabel {
    color: #8892b0;
    font-size: 11px;
}

QLabel#statusValue {
    font-size: 14px;
    font-weight: 600;
}

/* 上报状态区 */
QFrame#reportFrame {
    background-color: #16213e;
    border-radius: 10px;
    padding: 10px 12px;
}

QLabel#reportTitle {
    color: #8892b0;
    font-size: 12px;
    font-weight: 600;
}

QLabel#reportSummary {
    color: #8892b0;
    font-size: 11px;
}

QFrame#reportItem {
    background-color: #0f3460;
    border-radius: 4px;
    padding: 3px 8px;
}

QLabel#reportItemName {
    color: #cbd5e1;
    font-size: 11px;
}

QLabel#reportItemTime {
    color: #64748b;
    font-size: 10px;
}

/* 状态圆点 */
QFrame#dotOk {
    background-color: #10b981;
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}

QFrame#dotFail {
    background-color: #ef4444;
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}

QFrame#dotPartial {
    background-color: #f59e0b;
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}

QFrame#dotPending {
    background-color: #4b5563;
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}

/* 日志 Tab */
QTabWidget::pane {
    border: none;
    background-color: #16213e;
    border-radius: 0 0 10px 10px;
}

QTabWidget::tab-bar {
    alignment: left;
}

QTabBar {
    background-color: #16213e;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}

QTabBar::tab {
    background-color: transparent;
    color: #8892b0;
    padding: 8px 14px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 12px;
}

QTabBar::tab:selected {
    color: #60a5fa;
    border-bottom: 2px solid #4361ee;
}

QTabBar::tab:hover {
    color: #a0aec0;
}

QTextEdit {
    background-color: #16213e;
    color: #94a3b8;
    border: none;
    font-family: 'JetBrains Mono', 'Consolas', 'Menlo', monospace;
    font-size: 11px;
    padding: 8px;
}

/* 设置弹窗 */
QDialog {
    background-color: #1a1a2e;
}

QDialog QLabel {
    color: #e0e0e0;
    font-size: 12px;
}

QDialog QSpinBox, QDialog QLineEdit {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #2d3748;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}

QDialog QSpinBox:focus, QDialog QLineEdit:focus {
    border-color: #4361ee;
}

QDialog QCheckBox {
    color: #e0e0e0;
    font-size: 12px;
}

QDialog QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid #4b5563;
    background-color: #16213e;
}

QDialog QCheckBox::indicator:checked {
    background-color: #4361ee;
    border-color: #4361ee;
}

QDialog QPushButton {
    min-width: 60px;
}

/* 滚动条 */
QScrollBar:vertical {
    background-color: #16213e;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #2d3748;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #4b5563;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""
