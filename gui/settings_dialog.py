import json

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QPushButton, QFormLayout,
)

from config import SETTINGS_PATH


class SettingsDialog(QDialog):
    def __init__(self, current_collect: int, current_heartbeat: int, worker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self.setWindowTitle('设置')
        self.setFixedSize(320, 180)
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

        hint = QLabel('提示: 采集间隔建议 60-360 分钟，心跳间隔建议 15-30 分钟')
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

    def _save(self):
        collect = self._spin_collect.value()
        heartbeat = self._spin_heartbeat.value()

        settings = {'collect_interval': collect, 'heartbeat_interval': heartbeat}
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(settings, f)

        self._worker.update_intervals(collect, heartbeat)
        self.accept()
