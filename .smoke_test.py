"""离屏冒烟测试：真实构造 MainWindow（用桩模块屏蔽 playwright 等重依赖），
并模拟一次完整状态推送，覆盖构造期与信号处理路径，抓出所有 PySide6 类型/调用错误。
"""
import os
import sys
import types

# 1) 注册桩模块，避免 import 真实 worker / cookie_collector（它们依赖 playwright/browser）
PROJ = '/Users/yinhaowei/Desktop/yinhw/sto/StoCookie'
sys.path.insert(0, PROJ)

worker_mod = types.ModuleType('worker')
worker_mod.ZC_STATUS_LABEL = '客户经营分析状态'
sys.modules['worker'] = worker_mod

cc_mod = types.ModuleType('cookie_collector')
cc_mod.EXPECTED_REPORT_ITEMS = [
    {'label': 'WD_SESSION'}, {'label': 'spf_sid'}, {'label': 'Cookie_A'},
    {'label': 'Cookie_B'}, {'label': 'Cookie_C'},
]
sys.modules['cookie_collector'] = cc_mod

# 2) 假 worker（仅满足 MainWindow 构造与信号连接所需接口）
from PySide6.QtCore import QObject, Signal


class FakeSignals(QObject):
    log_message = Signal(str, str)
    status_update = Signal(dict)


class FakeWorker:
    def __init__(self):
        self.signals = FakeSignals()
        self.is_paused = False
        self.collect_interval = 60
        self.heartbeat_interval = 30

    def trigger_sync(self):
        pass

    def trigger_login(self):
        pass

    def pause(self):
        pass

    def resume(self):
        pass


# 3) 构造并测试
from PySide6.QtWidgets import QApplication
import gui.main_window as mw

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
app = QApplication([])

w = mw.MainWindow(FakeWorker())
w.show()
app.processEvents()

# 模拟一次完整状态推送
w._on_status({
    'account': 'testuser',
    'login': '已登录',
    'paused': False,
    'sync': '(12:00:00) 上报完成',
    'heartbeat': '正常',
    'next_collect': 120,
    'next_heartbeat': 60,
    'report_status': {
        'WD_SESSION': {'ok': True, 'time': '12:00:00'},
        'spf_sid': {'ok': False, 'error': '未采集到', 'time': '12:00:00'},
        'Cookie_A': {'ok': True, 'time': '12:00:00'},
        'Cookie_B': {'ok': False, 'error': '超时', 'time': '12:00:00'},
        'Cookie_C': {'ok': True, 'partial': True, 'time': '12:00:00'},
    },
    'pdd_status': {'SUB_PASS_ID (PDD)': {'ok': True, 'time': '12:00:00'}},
    'zc_status': {'客户经营分析状态': {'ok': True, 'time': '12:00:00'}},
})
app.processEvents()

# 触发一次计时 tick
w._tick()

# 测试暂停态 UI 驱动
w.set_paused_ui(True)
w.set_paused_ui(False)

# 测试日志面板 add（彩色行 + 各级别）
for msg in ('[成功] 登录完成 ✓', '[警告] 跳过本轮 ⚠', '[错误] 请求超时 ✗', '[信息] 心跳正常'):
    w._log_panel.add(msg, 'general')

app.processEvents()
print('SMOKE OK')
