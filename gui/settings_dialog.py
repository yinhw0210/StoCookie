import json
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QPushButton, QFormLayout, QCheckBox, QLineEdit,
    QFrame, QScrollArea, QWidget,
)
from PySide6.QtCore import Qt

from config import SETTINGS_PATH
from gui.styles import DARK_THEME


class _ProactiveRuleRow(QFrame):
    def __init__(self, rule: dict = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet('background-color: #0f3460; border-radius: 6px; padding: 6px;')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self._edit_cookie = QLineEdit(rule.get('cookie_name', '') if rule else '')
        self._edit_cookie.setPlaceholderText('cookie 名称，如 sid_cfo')
        self._edit_cookie.setMinimumWidth(140)

        self._spin_ttl = QSpinBox()
        self._spin_ttl.setRange(1, 720)
        self._spin_ttl.setValue(rule.get('ttl_hours', 12) if rule else 12)
        self._spin_ttl.setSuffix('h 过期')

        self._spin_advance = QSpinBox()
        self._spin_advance.setRange(1, 120)
        self._spin_advance.setValue(rule.get('advance_minutes', 10) if rule else 10)
        self._spin_advance.setSuffix('m 提前')

        self._btn_remove = QPushButton('✕')
        self._btn_remove.setFixedSize(22, 22)
        self._btn_remove.setStyleSheet(
            'background-color: #ef4444; color: white; border-radius: 4px; font-size: 11px; padding: 0;'
        )

        row1.addWidget(self._edit_cookie, stretch=1)
        row1.addWidget(self._spin_ttl)
        row1.addWidget(self._spin_advance)
        row1.addWidget(self._btn_remove)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self._edit_url = QLineEdit(rule.get('url', '') if rule else '')
        self._edit_url.setPlaceholderText('关联页面 URL（可选）')
        self._edit_url.setStyleSheet('font-size: 10px;')
        row2.addWidget(self._edit_url)
        layout.addLayout(row2)

    @property
    def remove_button(self):
        return self._btn_remove

    def to_dict(self) -> dict | None:
        cookie_name = self._edit_cookie.text().strip()
        if not cookie_name:
            return None
        return {
            'url': self._edit_url.text().strip(),
            'cookie_name': cookie_name,
            'ttl_hours': self._spin_ttl.value(),
            'advance_minutes': self._spin_advance.value(),
        }


class SettingsDialog(QDialog):
    def __init__(self, current_collect: int, current_heartbeat: int, worker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self.setWindowTitle('设置')
        self.setFixedSize(480, 560)
        self.setStyleSheet(DARK_THEME)
        self._proactive_rows: list[_ProactiveRuleRow] = []
        self._build_ui(current_collect, current_heartbeat)

    def _build_ui(self, current_collect: int, current_heartbeat: int):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 基础配置
        section_label = QLabel('基础配置')
        section_label.setStyleSheet('color: #60a5fa; font-size: 13px; font-weight: 600;')
        layout.addWidget(section_label)

        form = QFormLayout()
        form.setSpacing(8)

        self._spin_collect = QSpinBox()
        self._spin_collect.setRange(1, 1440)
        self._spin_collect.setValue(current_collect)
        self._spin_collect.setSuffix(' 分钟')
        form.addRow('采集上报间隔:', self._spin_collect)

        self._spin_heartbeat = QSpinBox()
        self._spin_heartbeat.setRange(1, 120)
        self._spin_heartbeat.setValue(current_heartbeat)
        self._spin_heartbeat.setSuffix(' 分钟')
        form.addRow('心跳保活间隔:', self._spin_heartbeat)

        layout.addLayout(form)

        # 分隔线
        self._add_separator(layout)

        # 预判刷新配置
        proactive_header = QHBoxLayout()
        proactive_label = QLabel('预判刷新')
        proactive_label.setStyleSheet('color: #60a5fa; font-size: 13px; font-weight: 600;')
        btn_add_rule = QPushButton('+ 添加规则')
        btn_add_rule.setObjectName('btnLogin')
        btn_add_rule.setFixedHeight(24)
        btn_add_rule.clicked.connect(self._add_proactive_rule)
        proactive_header.addWidget(proactive_label)
        proactive_header.addStretch()
        proactive_header.addWidget(btn_add_rule)
        layout.addLayout(proactive_header)

        proactive_hint = QLabel('到期前自动删除 cookie 并重新登录获取新 cookie')
        proactive_hint.setStyleSheet('color: #64748b; font-size: 11px;')
        layout.addWidget(proactive_hint)

        self._proactive_container = QVBoxLayout()
        self._proactive_container.setSpacing(6)
        layout.addLayout(self._proactive_container)

        # 加载已有规则
        settings = self._load_settings()
        for rule in settings.get('proactive_refresh', []):
            self._add_proactive_rule(rule)

        # 分隔线
        self._add_separator(layout)

        # PDD 配置
        pdd_label = QLabel('PDD 站点')
        pdd_label.setStyleSheet('color: #60a5fa; font-size: 13px; font-weight: 600;')
        layout.addWidget(pdd_label)

        self._chk_pdd_enabled = QCheckBox('启用 PDD 采集')
        self._chk_pdd_enabled.setChecked(settings.get('pdd_enabled', False))
        layout.addWidget(self._chk_pdd_enabled)

        pdd_form = QFormLayout()
        pdd_form.setSpacing(8)
        self._edit_pdd_account = QLineEdit(settings.get('pdd_account', ''))
        self._edit_pdd_account.setPlaceholderText('手机号')
        pdd_form.addRow('PDD 账号:', self._edit_pdd_account)

        self._edit_pdd_password = QLineEdit(settings.get('pdd_password', ''))
        self._edit_pdd_password.setPlaceholderText('密码')
        self._edit_pdd_password.setEchoMode(QLineEdit.EchoMode.Password)
        pdd_form.addRow('PDD 密码:', self._edit_pdd_password)
        layout.addLayout(pdd_form)

        hint = QLabel('PDD 配置修改后需重启程序生效')
        hint.setStyleSheet('color: #64748b; font-size: 11px;')
        layout.addWidget(hint)

        # 分隔线
        self._add_separator(layout)

        # 导出日志
        export_layout = QHBoxLayout()
        btn_export = QPushButton('导出日志')
        btn_export.setObjectName('btnLogin')
        btn_export.clicked.connect(self._export_logs)
        export_layout.addWidget(btn_export)
        export_layout.addStretch()
        layout.addLayout(export_layout)

        layout.addStretch()

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_save = QPushButton('保存')
        btn_save.setObjectName('btnSync')
        btn_cancel = QPushButton('取消')
        btn_cancel.setObjectName('btnLogin')
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        btn_save.clicked.connect(self._save)
        btn_cancel.clicked.connect(self.reject)

    def _add_separator(self, layout):
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet('background-color: #2d3748; max-height: 1px;')
        layout.addWidget(sep)

    def _add_proactive_rule(self, rule=None):
        if isinstance(rule, bool):
            rule = None
        row = _ProactiveRuleRow(rule)
        row.remove_button.clicked.connect(lambda: self._remove_proactive_rule(row))
        self._proactive_container.addWidget(row)
        self._proactive_rows.append(row)

    def _remove_proactive_rule(self, row: _ProactiveRuleRow):
        self._proactive_container.removeWidget(row)
        self._proactive_rows.remove(row)
        row.deleteLater()

    def _load_settings(self) -> dict:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, 'r') as f:
                return json.load(f)
        return {}

    def _save(self):
        collect = self._spin_collect.value()
        heartbeat = self._spin_heartbeat.value()

        # 收集预判刷新规则
        proactive_rules = []
        for row in self._proactive_rows:
            rule = row.to_dict()
            if rule:
                proactive_rules.append(rule)

        settings = self._load_settings()
        settings['collect_interval'] = collect
        settings['heartbeat_interval'] = heartbeat
        settings['proactive_refresh'] = proactive_rules
        settings['pdd_enabled'] = self._chk_pdd_enabled.isChecked()
        settings['pdd_account'] = self._edit_pdd_account.text().strip()
        settings['pdd_password'] = self._edit_pdd_password.text()

        with open(SETTINGS_PATH, 'w') as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)

        self._worker.update_intervals(collect, heartbeat)
        self.accept()

    def _export_logs(self):
        import platform
        from config import LOG_DIR
        if platform.system() == 'Darwin':
            os.system(f'open "{LOG_DIR}"')
        else:
            os.startfile(LOG_DIR)
