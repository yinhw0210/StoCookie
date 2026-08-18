# StoCookie 申通橙（STO）主题。集中管理配色与组件样式，保证整站统一。
# 配色：背景 #1b1c20 / 面板 #212329 / 工具栏级 #1d1f24 / 强调橙 #ff7a1a
#       成功 #3fb950 / 警告 #d29922 / 失败 #f85149 / 信息蓝 #58a6ff
#       主文字 #e6e7ea / 次文字 #9aa0a8 / 弱文字 #686d76

# ---- 颜色常量（单一事实来源，便于维护；QSS 不支持 CSS 变量，故在此集中管理）----
BG = "#1b1c20"              # 应用主背景
PANEL2 = "#1d1f24"          # 次级面板（顶部应用头，工具栏级）
PANEL = "#212329"           # 面板 / 卡片 / 上浮表面
BORDER = "#2c2f36"          # 边框 / 分隔线
BORDER_STRONG = "#3a3d45"   # 强边框 / hover 描边
DEEP = "#14161a"            # 更深背景（日志视图 / 趋势画布）
TITLE = "#16171a"           # 标题栏 / 状态栏（最深条）
TXT = "#e6e7ea"             # 主文字
SUB = "#9aa0a8"             # 次文字
MUTED = "#686d76"           # 弱文字
ACCENT = "#ff7a1a"          # 申通橙主强调
ACCENT_HOVER = "#ff9442"    # 强调 hover（更亮）
ACCENT_PRESSED = "#e96f12"  # 强调 pressed（更暗）
BTN_SEC_BG = "#26282e"      # 次要按钮底色
BTN_SEC_HOVER = "#2e3138"   # 次要按钮 hover
OK = "#3fb950"              # 成功
WARN = "#d29922"            # 警告
BAD = "#f85149"             # 错误 / 危险
INFO = "#58a6ff"            # 信息 / 重登中（维护态）

DARK_THEME = f"""
/* ===== 基础 ===== */
QMainWindow {{ background-color: {BG}; }}
QWidget#centralWidget {{ background-color: {BG}; }}

* {{ font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif; }}
QLabel {{ color: {TXT}; }}

/* ===== 顶部标题栏 ===== */
QFrame#appHeader {{
    background-color: {PANEL2};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 14px;
}}
QLabel#appTitle {{ color: {TXT}; font-size: 16px; font-weight: 700; }}
QLabel#appSubtitle {{ color: {SUB}; font-size: 11px; }}
QFrame#titleDot {{
    background-color: {ACCENT}; border-radius: 6px;
    min-width: 12px; max-width: 12px; min-height: 12px; max-height: 12px;
}}

/* 状态药丸 */
QFrame#statePill {{ border-radius: 14px; }}
QLabel#pillText {{ font-size: 12px; font-weight: 600; color: {SUB}; }}
QFrame#pillDot {{ border-radius: 4px; }}

/* 账号芯片 */
QFrame#accountChip {{
    background-color: {PANEL}; border: 1px solid {BORDER};
    border-radius: 14px; padding: 4px 12px;
}}
QLabel#accountText {{ color: {TXT}; font-size: 12px; }}
QFrame#accountDot {{
    background-color: {OK}; border-radius: 4px;
    min-width: 7px; max-width: 7px; min-height: 7px; max-height: 7px;
}}

/* ===== 按钮（基类防白底） ===== */
QPushButton {{
    background-color: {BTN_SEC_BG}; color: {TXT};
    border: 1px solid {BORDER}; border-radius: 8px;
    padding: 8px 16px; font-size: 12px; font-weight: 600;
}}
QPushButton#btnSync, QPushButton#btnPrimary {{
    background-color: {ACCENT}; color: #1b1c20; border: 1px solid {ACCENT};
}}
QPushButton#btnSync:hover, QPushButton#btnPrimary:hover {{
    background-color: {ACCENT_HOVER}; border-color: {ACCENT_HOVER};
}}
QPushButton#btnSync:pressed, QPushButton#btnPrimary:pressed {{
    background-color: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED};
}}
QPushButton#btnLogin, QPushButton#btnSettings, QPushButton#btnPause {{
    background-color: {BTN_SEC_BG}; color: {TXT}; border: 1px solid {BORDER};
}}
QPushButton#btnLogin:hover, QPushButton#btnSettings:hover, QPushButton#btnPause:hover {{
    background-color: {BTN_SEC_HOVER}; border-color: {BORDER_STRONG};
}}
QPushButton#btnGhost {{
    background-color: transparent; color: {SUB};
    border: 1px solid {BORDER};
}}
QPushButton#btnGhost:hover {{ color: {TXT}; border-color: {BORDER_STRONG}; }}
QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton#btnLogin:focus, QPushButton#btnSettings:focus, QPushButton#btnPause:focus {{ border: 1px solid {ACCENT}; }}
QPushButton#logChip:focus {{ border: 1px solid {ACCENT}; }}

/* ===== KPI 指标卡 ===== */
QFrame#metricCard {{
    background-color: {PANEL}; border: 1px solid {BORDER};
    border-radius: 12px; padding: 12px 14px;
}}
QLabel#metricLabel {{ color: {SUB}; font-size: 11px; }}
QLabel#metricValue {{ font-size: 22px; font-weight: 700; color: {TXT}; }}
QLabel#metricSub {{ color: {MUTED}; font-size: 10px; }}

/* ===== 区块标题 ===== */
QWidget#sectionTitle {{ background: transparent; }}
QFrame#sectionBar {{
    background-color: {ACCENT}; border-radius: 2px;
    min-width: 3px; max-width: 3px; min-height: 14px; max-height: 14px;
}}
QLabel#sectionTitleText {{ color: {TXT}; font-size: 13px; font-weight: 600; }}

/* ===== 上报明细分组 ===== */
QFrame#reportGroup {{
    background-color: {PANEL}; border: 1px solid {BORDER};
    border-radius: 12px; padding: 12px 14px;
}}
QLabel#reportGroupTitle {{
    color: {TXT}; font-size: 12px; font-weight: 700;
    padding-bottom: 6px;
}}
QFrame#reportRow {{
    background-color: {PANEL}; border-radius: 8px;
    padding: 5px 10px;
}}
QLabel#reportRowName {{ color: {TXT}; font-size: 12px; }}
QLabel#reportRowTime {{ color: {MUTED}; font-size: 10px; }}

/* ===== 趋势图容器 ===== */
QFrame#trendWidget {{
    background-color: {PANEL}; border: 1px solid {BORDER};
    border-radius: 12px; padding: 12px 14px;
}}
QLabel#trendStat {{ color: {SUB}; font-size: 11px; }}
QLabel#trendBig {{ font-size: 18px; font-weight: 700; }}

/* ===== 日志面板 ===== */
QWidget#logPanel {{ background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; padding: 12px; }}
QPushButton#logChip {{
    background-color: {PANEL}; color: {SUB};
    border: 1px solid {BORDER}; border-radius: 12px;
    padding: 4px 12px; font-size: 11px; font-weight: 500;
}}
QPushButton#logChip:checked {{
    background-color: {ACCENT}; color: #1b1c20; border-color: {ACCENT};
}}
QPushButton#logChip:hover {{ color: {TXT}; }}
QLineEdit#logSearch {{
    background-color: {PANEL}; color: {TXT};
    border: 1px solid {BORDER}; border-radius: 8px;
    padding: 5px 10px; font-size: 12px;
}}
QLineEdit#logSearch:focus {{ border-color: {ACCENT}; }}
QPlainTextEdit#logView {{
    background-color: {DEEP}; color: {SUB};
    border: 1px solid {BORDER}; border-radius: 8px;
    font-family: "JetBrains Mono", "Consolas", "Menlo", monospace;
    font-size: 11px; padding: 8px;
}}

/* ===== 底部状态条 ===== */
QFrame#statusBar {{ background-color: {TITLE}; border-radius: 10px; padding: 6px 12px; }}
QLabel#statusText {{ color: {SUB}; font-size: 11px; }}
QFrame#connDot {{
    background-color: {OK}; border-radius: 4px;
    min-width: 7px; max-width: 7px; min-height: 7px; max-height: 7px;
}}

/* ===== 通用文本 ===== */
QLabel#muted {{ color: {MUTED}; font-size: 11px; }}

/* ===== 滚动区（防白底关键） ===== */
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget#qt_scrollarea_viewport {{ background-color: {BG}; }}
QWidget#scrollBody {{ background-color: {BG}; }}
QScrollBar:vertical {{ background-color: {TITLE}; width: 8px; border-radius: 4px; }}
QScrollBar::handle:vertical {{ background-color: {BORDER}; border-radius: 4px; min-height: 20px; }}
QScrollBar::handle:vertical:hover {{ background-color: {BORDER_STRONG}; }}
QScrollBar:horizontal {{ background-color: {TITLE}; height: 8px; border-radius: 4px; }}
QScrollBar::handle:horizontal {{ background-color: {BORDER}; border-radius: 4px; min-width: 20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ height: 0; width: 0; }}

/* ===== 输入框兜底（零白底） ===== */
QLineEdit, QSpinBox {{
    background-color: {PANEL}; color: {TXT};
    border: 1px solid {BORDER}; border-radius: 6px;
    padding: 4px 8px; font-size: 12px;
}}
QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit::placeholder {{ color: {MUTED}; }}

/* ===== 文本编辑兜底 ===== */
QPlainTextEdit {{ background-color: {DEEP}; color: {SUB}; border: 1px solid {BORDER}; border-radius: 8px; }}

/* ===== 复选框标签兜底 ===== */
QCheckBox {{ color: {TXT}; spacing: 6px; }}

/* ===== 工具提示（防白） ===== */
QToolTip {{
    background-color: {TITLE}; color: {TXT};
    border: 1px solid {BORDER}; border-radius: 6px;
    padding: 4px 8px; font-size: 11px;
}}

/* ===== 日志 Tab(保留兼容) ===== */
QTabWidget::pane {{ border: none; background-color: {PANEL}; border-radius: 0 0 10px 10px; }}
QTabWidget::tab-bar {{ alignment: left; }}
QTabBar {{ background-color: {PANEL2}; }}
QTabBar::tab {{
    background-color: transparent; color: {SUB};
    padding: 8px 14px; border: none; border-bottom: 2px solid transparent; font-size: 12px;
}}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: #c9cdd4; }}

QTextEdit {{
    background-color: {DEEP}; color: {SUB}; border: none;
    font-family: "JetBrains Mono", "Consolas", "Menlo", monospace;
    font-size: 11px; padding: 8px;
}}

/* ===== 设置弹窗 ===== */
QDialog {{ background-color: {BG}; }}
QDialog QLabel {{ color: {TXT}; font-size: 12px; }}
QDialog QSpinBox, QDialog QLineEdit {{
    background-color: {PANEL}; color: {TXT};
    border: 1px solid {BORDER}; border-radius: 6px;
    padding: 4px 8px; font-size: 12px;
}}
QDialog QSpinBox:focus, QDialog QLineEdit:focus {{ border-color: {ACCENT}; }}
QDialog QCheckBox {{ color: {TXT}; font-size: 12px; }}
QDialog QCheckBox::indicator {{
    width: 14px; height: 14px; border-radius: 3px;
    border: 1px solid {BORDER_STRONG}; background-color: {PANEL};
}}
QDialog QCheckBox::indicator:checked {{ background-color: {ACCENT}; border-color: {ACCENT}; }}
QDialog QPushButton {{ min-width: 60px; }}
"""
