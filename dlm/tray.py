"""系统托盘。左键或菜单都可以打开设置；退出时把收尾交给主线程。"""

from __future__ import annotations

import logging
import os
import sys
import threading

from dlm import __version__
from dlm.notify import open_file_location, open_folder
from dlm.paths import log_path

log = logging.getLogger("DLM")

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    pystray = None
    HAS_TRAY = False


def _icon_image():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 62, 62), 14, fill=(0, 103, 192, 255))
    draw.rounded_rectangle((16, 28, 48, 48), 3, fill="white")
    draw.polygon([(22, 28), (32, 16), (42, 28)], fill="white")
    draw.rectangle((29, 32, 35, 44), fill=(0, 103, 192, 255))
    return image


def _install_left_click(icon, opener) -> None:
    try:
        from pystray._win32 import win32 as bridge
    except Exception as exc:
        log.info("托盘左键快捷方式不可用，请用菜单里的「打开设置」(%s)", exc)
        return
    message = getattr(bridge, "WM_NOTIFY", None)
    handlers = getattr(icon, "_message_handlers", None)
    if message is None or not handlers or message not in handlers:
        return
    original = handlers[message]

    def patched(wparam, lparam):
        if lparam == 0x0202:
            opener()
            return True
        return original(wparam, lparam)

    handlers[message] = patched


def setup_tray(app) -> bool:
    if not HAS_TRAY:
        log.warning("未安装 pystray 或 Pillow，系统托盘不可用")
        return False

    from dlm.config import load_config
    from dlm.paths import config_path
    from dlm.settings_window import focus_settings, show_settings_window

    gate = threading.Lock()
    cfg_file = config_path()

    def open_settings(_icon=None, _item=None) -> None:
        if focus_settings():
            return
        if not gate.acquire(blocking=False):
            return

        def run() -> None:
            try:
                try:
                    fresh = load_config(cfg_file)
                except Exception:
                    fresh = app.cfg
                result = show_settings_window(fresh, cfg_file, version=__version__)
                if result and result.get("applied") and result.get("config"):
                    app.apply_config(result["config"])
            except Exception:
                log.exception("设置窗口出错")
            finally:
                gate.release()

        threading.Thread(target=run, name="dlm-settings", daemon=True).start()

    def toggle_pause(_icon, _item) -> None:
        paused = app.handler.toggle_user_paused()
        log.info("监控已暂停" if paused else "监控已继续")
        try:
            _icon.update_menu()
        except Exception:
            pass

    def open_target(_icon=None, _item=None) -> None:
        target = app.handler.target_path()
        if target is None:
            log.warning("还没有设置目标目录")
            return
        open_folder(target)

    def open_log(_icon=None, _item=None) -> None:
        path = log_path()
        if path.exists():
            open_file_location(path)
        else:
            open_folder(path.parent)

    def about(_icon=None, _item=None) -> None:
        text = (
            f"下载分类管家 v{__version__}\n\n"
            "自动整理下载文件夹。\n"
            "默认只移动或复制，重复文件会放到「重复文件」。\n\n"
            "https://github.com/fanAa8/download-manager"
        )

        def run() -> None:
            try:
                import tkinter as tk
                from tkinter import messagebox

                root = tk.Tk()
                root.withdraw()
                messagebox.showinfo("关于", text, parent=root)
                root.destroy()
            except Exception:
                log.info(text)

        threading.Thread(target=run, daemon=True).start()

    def do_exit(icon, _item) -> None:
        try:
            icon.stop()
        except Exception:
            os._exit(0)
        timer = threading.Timer(8, lambda: os._exit(0))
        timer.daemon = True
        timer.start()

    menu = pystray.Menu(
        pystray.MenuItem("打开设置", open_settings, default=True),
        pystray.MenuItem("暂停监控", toggle_pause, checked=lambda _item: app.handler.user_paused),
        pystray.MenuItem("打开目标文件夹", open_target),
        pystray.MenuItem("打开日志", open_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("关于", about),
        pystray.MenuItem("退出", do_exit),
    )
    icon = pystray.Icon("download_manager", _icon_image(), "下载分类管家", menu)
    _install_left_click(icon, open_settings)
    if sys.platform != "win32":
        log.warning("当前不是 Windows，托盘图标可能无法显示")
    icon.run()
    return True
