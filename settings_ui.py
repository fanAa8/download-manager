"""兼容旧的导入路径。界面和托盘的实现在 dlm 包里。"""

from pathlib import Path

from dlm.files import transfer as _transfer


def smart_move(src, dst) -> bool:
    """移动到目标路径。目标已存在时不覆盖，失败时原文件保留。"""
    return _transfer(Path(src), Path(dst), "move")


def __getattr__(name):
    if name == "_show_settings_window":
        from dlm.settings_window import show_settings_window

        return show_settings_window
    if name == "setup_tray":
        from dlm.tray import setup_tray

        return setup_tray
    raise AttributeError(name)


__all__ = ["smart_move", "_show_settings_window", "setup_tray"]
