import json
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QPushButton, QFormLayout, QCheckBox, QLineEdit,
)

from config import SETTINGS_PATH


class SettingsDialog(QDialog):
    def __init__(self, current_collect: int, current_heartbeat: int, worker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self.setWindowTitle('设置')
        self.setFixedSize(380, 320)
        self._build_ui(current_collect, current_heartbeat)

    def _build_ui(self, current_collect: int, current_heartbeat: int):
        layout = QVBoxLayout(self)

        form = QFormLayout()

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

        # PDD 配置区域
        pdd_label = QLabel('--- PDD 站点 ---')
        pdd_label.setStyleSheet('font-weight: bold; margin-top: 10px;')
        layout.addWidget(pdd_label)

        settings = self._load_settings()

        self._chk_pdd_enabled = QCheckBox('启用 PDD 采集')
        self._chk_pdd_enabled.setChecked(settings.get('pdd_enabled', False))
        layout.addWidget(self._chk_pdd_enabled)

        pdd_form = QFormLayout()
        self._edit_pdd_account = QLineEdit(settings.get('pdd_account', ''))
        self._edit_pdd_account.setPlaceholderText('手机号')
        pdd_form.addRow('PDD 账号:', self._edit_pdd_account)

        self._edit_pdd_password = QLineEdit(settings.get('pdd_password', ''))
        self._edit_pdd_password.setPlaceholderText('密码')
        self._edit_pdd_password.setEchoMode(QLineEdit.EchoMode.Password)
        pdd_form.addRow('PDD 密码:', self._edit_pdd_password)
        layout.addLayout(pdd_form)

        hint = QLabel('提示: PDD 配置修改后需重启程序生效')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: gray; font-size: 11px;')
        layout.addWidget(hint)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton('保存')
        btn_cancel = QPushButton('取消')
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
