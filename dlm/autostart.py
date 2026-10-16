"""当前用户的开机启动项。只写 HKCU，不需要管理员。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "DownloadClassifierManager"
_STARTUP_LINK = (
    Path(os.environ.get("APPDATA", "."))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
    / "下载分类管家.lnk"
)


def is_autostart() -> bool:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.QueryValueEx(key, _APP_NAME)
            return True
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return _STARTUP_LINK.exists()


def set_autostart(enable: bool) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                exe = str(Path(sys.executable).resolve())
                winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
            else:
                try:
                    winreg.DeleteValue(key, _APP_NAME)
                except FileNotFoundError:
                    pass
        if not enable:
            try:
                _STARTUP_LINK.unlink(missing_ok=True)
            except OSError:
                pass
        return True
    except OSError:
        return False
