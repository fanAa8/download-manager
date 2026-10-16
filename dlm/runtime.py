"""进程内共享的运行实例，方便设置窗口在手动整理时暂停监控。"""


class Runtime:
    def __init__(self) -> None:
        self.app = None


RUNTIME = Runtime()
