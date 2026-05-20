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
        self._signal.emit(message.strip())


def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level='INFO')
    logger.add(
        os.path.join(LOG_DIR, 'stocookie.log'),
        rotation='10 MB', retention='7 days', level='DEBUG',
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    worker = BackgroundWorker()

    logger.add(QtLogSink(worker.signals.log_message), format='{time:HH:mm:ss} {message}', level='INFO')

    window = MainWindow(worker)
    tray = TrayIcon(window, worker)
    tray.show()
    window.show()

    worker.start()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
