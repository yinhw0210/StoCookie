from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QPushButton, QFormLayout, QCheckBox, QLineEdit,
    QFrame, QScrollArea, QWidget, QMessageBox, QApplication,
)
from PySide6.QtCore import Qt

from config import SETTINGS_PATH, load_settings, save_settings
from gui.styles import DARK_THEME


class SettingsDialog(QDialog):
    def __init__(self, current_collect: int, current_heartbeat: int, worker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self.setWindowTitle('设置')
        self.setStyleSheet(DARK_THEME)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        # Playwright 会拉起最大化 Chromium，设置窗必须置顶，否则像点了没开。
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._build_ui(current_collect, current_heartbeat)
        self._fit_to_screen()

    def _fit_to_screen(self):
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        width = 500
        height = 720
        if avail:
            width = min(500, max(420, avail.width() - 80))
            height = min(720, max(360, avail.height() - 80))
            self.resize(width, height)
            frame = self.frameGeometry()
            frame.moveCenter(avail.center())
            self.move(frame.topLeft())
        else:
            self.resize(width, height)
        self.setMinimumSize(420, 360)

    def _build_ui(self, current_collect: int, current_heartbeat: int):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName('scrollBody')
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        settings = load_settings()

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

        self._add_separator(layout)

        # PDD 配置
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

        hint = QLabel('保存后立即用新账号重新登录 PDD，无需重启程序')
        hint.setStyleSheet('color: #686d76; font-size: 11px;')
        hint.setWordWrap(True)
        layout.addWidget(hint)

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
        zc_hint.setWordWrap(True)
        layout.addWidget(zc_hint)

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

        self._add_separator(layout)

        export_layout = QHBoxLayout()
        btn_export = QPushButton('导出日志')
        btn_export.setObjectName('btnLogin')
        btn_export.clicked.connect(self._export_logs)
        export_layout.addWidget(btn_export)
        export_layout.addStretch()
        layout.addLayout(export_layout)

        path_hint = QLabel(f'配置文件：{SETTINGS_PATH}')
        path_hint.setStyleSheet('color: #686d76; font-size: 10px;')
        path_hint.setWordWrap(True)
        layout.addWidget(path_hint)

        layout.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton('保存')
        btn_save.setObjectName('btnSync')
        btn_cancel = QPushButton('取消')
        btn_cancel.setObjectName('btnLogin')
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        outer.addLayout(btn_layout)

        btn_save.clicked.connect(self._save)
        btn_cancel.clicked.connect(self.reject)

    def _add_separator(self, layout):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet('background-color: #2c2f36; max-height: 1px;')
        layout.addWidget(sep)

    def _save(self):
        collect = self._spin_collect.value()
        heartbeat = self._spin_heartbeat.value()
        pdd_enabled = self._chk_pdd_enabled.isChecked()
        pdd_account = self._edit_pdd_account.text().strip()
        pdd_password = self._edit_pdd_password.text()
        zc_enabled = self._chk_zc_enabled.isChecked()
        zc_interval = self._spin_zc_interval.value()
        kunlun_enabled = self._chk_kunlun_enabled.isChecked()
        kunlun_heartbeat = self._spin_kunlun_heartbeat.value()

        try:
            save_settings({
                'collect_interval': collect,
                'heartbeat_interval': heartbeat,
                'pdd_enabled': pdd_enabled,
                'pdd_account': pdd_account,
                'pdd_password': pdd_password,
                'zc_enabled': zc_enabled,
                'zc_interval': zc_interval,
                'kunlun_enabled': kunlun_enabled,
                'kunlun_heartbeat_interval': kunlun_heartbeat,
            })
        except OSError as e:
            QMessageBox.critical(self, '保存失败', f'无法写入配置文件：\n{SETTINGS_PATH}\n\n{e}')
            return

        self._worker.update_intervals(collect, heartbeat)
        self._worker.update_zc_settings(zc_enabled, zc_interval)
        self._worker.update_kunlun_settings(kunlun_enabled, kunlun_heartbeat)
        self._worker.update_pdd_settings(pdd_enabled, pdd_account, pdd_password)
        self.accept()

    def _export_logs(self):
        import platform
        from config import LOG_DIR
        os.makedirs(LOG_DIR, exist_ok=True)
        if platform.system() == 'Darwin':
            os.system(f'open "{LOG_DIR}"')
        else:
            os.startfile(LOG_DIR)
