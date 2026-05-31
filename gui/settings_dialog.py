import json
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QPushButton, QFormLayout, QCheckBox, QLineEdit,
    QFrame,
)
from PySide6.QtCore import Qt

from config import SETTINGS_PATH
from gui.styles import DARK_THEME


class SettingsDialog(QDialog):
    def __init__(self, current_collect: int, current_heartbeat: int, worker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self.setWindowTitle('设置')
        self.setFixedSize(420, 400)
        self.setStyleSheet(DARK_THEME)
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
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet('background-color: #2d3748; max-height: 1px;')
        layout.addWidget(sep1)

        # PDD 配置
        pdd_label = QLabel('PDD 站点')
        pdd_label.setStyleSheet('color: #60a5fa; font-size: 13px; font-weight: 600;')
        layout.addWidget(pdd_label)

        settings = self._load_settings()

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
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet('background-color: #2d3748; max-height: 1px;')
        layout.addWidget(sep2)

        # 导出日志按钮
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

        with open(SETTINGS_PATH, 'w') as f:
            json.dump(settings, f, ensure_ascii=False)

        self._worker.update_intervals(collect, heartbeat)
        self.accept()

    def _export_logs(self):
        import platform
        from config import LOG_DIR
        if platform.system() == 'Darwin':
            os.system(f'open "{LOG_DIR}"')
        else:
            os.startfile(LOG_DIR)
