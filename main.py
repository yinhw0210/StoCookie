import sys
import os

from PySide6.QtWidgets import QApplication
from loguru import logger

from config import LOG_DIR
from worker import BackgroundWorker
from gui.main_window import MainWindow
from gui.tray_icon import TrayIcon


class QtLogSink:
    def __init__(self, signal):
        self._signal = signal

    def write(self, message):
        self._signal.emit(message.strip(), 'general')


def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level='INFO', diagnose=False, backtrace=False)
    logger.add(
        os.path.join(LOG_DIR, 'stocookie-{time:YYYY-MM-DD}.log'),
        rotation='00:00', retention='30 days', level='DEBUG',
        diagnose=False, backtrace=False,
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    worker = BackgroundWorker()

    # 注意：worker._emit_log 已直接 emit 到 GUI，不再通过 loguru 重复转发
    # logger.add(QtLogSink(worker.signals.log_message), format='{time:HH:mm:ss} {message}', level='INFO')

    window = MainWindow(worker)
    tray = TrayIcon(window, worker)
    window.set_tray(tray)
    # 托盘菜单与主窗口共享暂停态：worker 推送的 paused 状态同步到托盘
    worker.signals.status_update.connect(tray.on_status)
    tray.show()
    window.show()

    worker.start()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
