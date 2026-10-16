"""通知和在资源管理器中定位文件。非 Windows 环境只写日志。"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("DLM")


def open_file_location(path: Path) -> None:
    target = Path(path)
    if sys.platform != "win32":
        log.info("定位: %s", target)
        return
    resolved = str(target.resolve()) if target.exists() else str(target)
    try:
        import ctypes

        ctypes.windll.shell32.ShellExecuteW(0, "open", "explorer.exe", f'/select,"{resolved}"', None, 1)
    except Exception:
        try:
            subprocess.run(f'explorer /select,"{resolved}"', shell=True, timeout=10)
        except Exception as exc:
            log.warning("无法打开资源管理器 (%s)", exc)


def open_folder(path: Path) -> None:
    target = Path(path)
    if not target.exists():
        log.warning("路径不存在: %s", target)
        return
    if sys.platform == "win32":
        try:
            import os

            os.startfile(target)  # type: ignore[attr-defined]
            return
        except OSError as exc:
            log.warning("无法打开 %s (%s)", target, exc)
            return
    command = ["open", str(target)] if sys.platform == "darwin" else ["xdg-open", str(target)]
    try:
        subprocess.Popen(command)
    except OSError as exc:
        log.warning("无法打开 %s (%s)", target, exc)


def show_toast(title: str, message: str, click_callback=None, timeout_ms: int = 4000) -> None:
    log.info("%s — %s", title, message)
    if sys.platform != "win32":
        return
    threading.Thread(
        target=_toast,
        args=(title, message, click_callback, timeout_ms),
        daemon=True,
    ).start()


def _toast(title: str, message: str, callback, timeout_ms: int) -> None:
    try:
        import tkinter as tk

        from dlm.theme import palette
    except Exception as exc:
        log.debug("通知未显示 (%s)", exc)
        return
    colors = palette()
    try:
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        width, height = 380, 64
        root.update_idletasks()
        x = root.winfo_screenwidth() - width - 24
        y = root.winfo_screenheight() - height - 72
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.configure(bg=colors.bg, highlightthickness=1, highlightbackground=colors.border)
        frame = tk.Frame(root, bg=colors.surface, cursor="hand2" if callback else "arrow")
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame, text=title, font=("Microsoft YaHei UI", 9, "bold"),
            bg=colors.surface, fg=colors.fg, anchor="w",
        ).pack(anchor="w", padx=14, pady=(8, 0))
        shown = message if len(message) <= 48 else "…" + message[-46:]
        tk.Label(
            frame, text=shown, font=("Microsoft YaHei UI", 8),
            bg=colors.surface, fg=colors.muted, anchor="w",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        def _click(_event=None):
            if callback is not None:
                try:
                    callback()
                except Exception as exc:
                    log.debug("通知点击失败 (%s)", exc)
            root.destroy()

        if callback is not None:
            frame.bind("<Button-1>", _click)
            for child in frame.winfo_children():
                child.bind("<Button-1>", _click)
        root.after(timeout_ms, root.destroy)
        root.deiconify()
        root.mainloop()
    except Exception as exc:
        log.debug("通知未显示 (%s)", exc)
