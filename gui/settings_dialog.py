from __future__ import annotations

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


class SettingsDialog(QDialog):
    def __init__(self, current_collect: int, current_heartbeat: int, worker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self.setWindowTitle('设置')
        self.setFixedSize(480, 760)
        self.setStyleSheet(DARK_THEME)
        self._build_ui(current_collect, current_heartbeat)

    def _build_ui(self, current_collect: int, current_heartbeat: int):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 基础配置
        section_label = QLabel('基础配置')
        section_label.setStyleSheet('color: #e6e7ea; font-size: 13px; font-weight: 600;')
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

        # PDD 配置
        settings = self._load_settings()
        pdd_label = QLabel('PDD 站点')
        pdd_label.setStyleSheet('color: #e6e7ea; font-size: 13px; font-weight: 600;')
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
        hint.setStyleSheet('color: #686d76; font-size: 11px;')
        layout.addWidget(hint)

        # 分隔线
        self._add_separator(layout)

        # 客户经营分析 engineSid 配置
        zc_label = QLabel('客户经营分析 (engineSid)')
        zc_label.setStyleSheet('color: #e6e7ea; font-size: 13px; font-weight: 600;')
        layout.addWidget(zc_label)

        self._chk_zc_enabled = QCheckBox('启用 engineSid 采集')
        self._chk_zc_enabled.setChecked(settings.get('zc_enabled', True))
        layout.addWidget(self._chk_zc_enabled)

        zc_form = QFormLayout()
        zc_form.setSpacing(8)
        self._spin_zc_interval = QSpinBox()
        self._spin_zc_interval.setRange(1, 1440)
        self._spin_zc_interval.setValue(settings.get('zc_interval', 30))
        self._spin_zc_interval.setSuffix(' 分钟')
        zc_form.addRow('engineSid 刷新间隔:', self._spin_zc_interval)
        layout.addLayout(zc_form)

        zc_hint = QLabel('每次刷新页面 engineSid 都会变；独立时间线，间隔修改后即时生效')
        zc_hint.setStyleSheet('color: #686d76; font-size: 11px;')
        layout.addWidget(zc_hint)

        # 分隔线
        self._add_separator(layout)

        # 昆仑 kunlun_stotoken 配置
        kunlun_label = QLabel('昆仑扫描查询 (kunlun_stotoken)')
        kunlun_label.setStyleSheet('color: #e6e7ea; font-size: 13px; font-weight: 600;')
        layout.addWidget(kunlun_label)

        self._chk_kunlun_enabled = QCheckBox('启用昆仑采集')
        self._chk_kunlun_enabled.setChecked(settings.get('kunlun_enabled', True))
        layout.addWidget(self._chk_kunlun_enabled)

        kunlun_form = QFormLayout()
        kunlun_form.setSpacing(8)
        self._spin_kunlun_heartbeat = QSpinBox()
        self._spin_kunlun_heartbeat.setRange(1, 1440)
        self._spin_kunlun_heartbeat.setValue(settings.get('kunlun_heartbeat_interval', 30))
        self._spin_kunlun_heartbeat.setSuffix(' 分钟')
        kunlun_form.addRow('昆仑心跳间隔:', self._spin_kunlun_heartbeat)
        layout.addLayout(kunlun_form)

        kunlun_hint = QLabel('独立 Context + 钉钉 SSO；启用开关需重启生效，心跳间隔即时生效；上报对齐采集间隔')
        kunlun_hint.setStyleSheet('color: #686d76; font-size: 11px;')
        kunlun_hint.setWordWrap(True)
        layout.addWidget(kunlun_hint)

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
        sep.setStyleSheet('background-color: #2c2f36; max-height: 1px;')
        layout.addWidget(sep)

    def _load_settings(self) -> dict:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, 'r') as f:
                return json.load(f)
        return {}

    def _save(self):
        collect = self._spin_collect.value()
        heartbeat = self._spin_heartbeat.value()

        settings = self._load_settings()
        settings['collect_interval'] = collect
        settings['heartbeat_interval'] = heartbeat
        settings['pdd_enabled'] = self._chk_pdd_enabled.isChecked()
        settings['pdd_account'] = self._edit_pdd_account.text().strip()
        settings['pdd_password'] = self._edit_pdd_password.text()
        settings['zc_enabled'] = self._chk_zc_enabled.isChecked()
        settings['zc_interval'] = self._spin_zc_interval.value()
        settings['kunlun_enabled'] = self._chk_kunlun_enabled.isChecked()
        settings['kunlun_heartbeat_interval'] = self._spin_kunlun_heartbeat.value()

        with open(SETTINGS_PATH, 'w') as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)

        self._worker.update_intervals(collect, heartbeat)
        self._worker.update_zc_settings(settings['zc_enabled'], settings['zc_interval'])
        self._worker.update_kunlun_settings(
            settings['kunlun_enabled'], settings['kunlun_heartbeat_interval']
        )
        self.accept()

    def _export_logs(self):
        import platform
        from config import LOG_DIR
        if platform.system() == 'Darwin':
            os.system(f'open "{LOG_DIR}"')
        else:
            os.startfile(LOG_DIR)
