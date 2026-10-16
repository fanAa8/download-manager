"""运行时路径。源码运行和 PyInstaller 单文件都从这里取位置。"""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """配置、数据库和日志所在目录：exe 旁边，或仓库根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dirs() -> list[Path]:
    """只读资源目录：打包临时目录，以及程序目录。"""
    dirs: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass))
    dirs.append(app_dir())
    return dirs


def config_path() -> Path:
    return app_dir() / "config.json"


def default_config_path() -> Path | None:
    for folder in resource_dirs():
        candidate = folder / "config.default.json"
        if candidate.is_file():
            return candidate
    return None


def db_path() -> Path:
    return app_dir() / "download_manager.db"


def log_path() -> Path:
    return app_dir() / "download_manager.log"
