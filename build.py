#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把下载分类管家打成 Windows 绿色版。

    python build.py --dry-run     检查打包参数（任意系统）
    python build.py               在 Windows 上生成 exe 和 zip
    python build.py --console     带控制台，方便看报错
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

from dlm import __version__

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
RELEASE = HERE / "release"
EXE_NAME = "下载分类管家.exe"


def module_names() -> list[str]:
    names = ["dlm", "settings_ui"]
    package = HERE / "dlm"
    for path in sorted(package.glob("*.py")):
        if path.name == "__init__.py":
            continue
        names.append(f"dlm.{path.stem}")
    extras = [
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "watchdog",
        "watchdog.observers",
        "watchdog.events",
        "sqlite3",
        "winreg",
        "ctypes",
        "ctypes.wintypes",
        "send2trash",
        "pystray",
        "pystray._win32",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
    ]
    for name in extras:
        if name not in names:
            names.append(name)
    return names


def pyinstaller_args(console: bool) -> list[str]:
    config = HERE / "config.default.json"
    if not config.is_file():
        raise SystemExit(f"缺少 {config.name}")
    separator = ";" if sys.platform == "win32" else ":"
    args = [
        str(HERE / "download_manager.py"),
        "--name", EXE_NAME.replace(".exe", ""),
        "--onefile",
        "--console" if console else "--windowed",
        "--clean",
        "--noconfirm",
        "--distpath", str(DIST),
        "--workpath", str(HERE / "build"),
        "--specpath", str(HERE / "build"),
        "--add-data", f"{config}{separator}.",
        "--collect-submodules", "dlm",
    ]
    for name in module_names():
        args.extend(["--hidden-import", name])
    for name in ("matplotlib", "numpy", "pandas", "scipy"):
        args.extend(["--exclude-module", name])
    return args


def stage_release(exe: Path) -> Path:
    folder = RELEASE / f"下载分类管家-v{__version__}-windows"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    shutil.copy2(exe, folder / EXE_NAME)
    for name in ("config.default.json", "install.bat", "README.md", "LICENSE", "CHANGELOG.md"):
        source = HERE / name
        if source.is_file():
            shutil.copy2(source, folder / name)
    archive = RELEASE / f"下载分类管家-v{__version__}-windows.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in folder.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(RELEASE).as_posix())
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打包下载分类管家")
    parser.add_argument("--dry-run", action="store_true", help="只打印打包计划")
    parser.add_argument("--console", action="store_true", help="保留控制台窗口")
    args = parser.parse_args(argv)
    plan = pyinstaller_args(args.console)
    print(f"下载分类管家 v{__version__}")
    print(f"入口: download_manager.py")
    print(f"隐藏导入: {len(module_names())} 个")
    if args.dry_run:
        print("dry-run 通过。Windows 上执行 python build.py 才会生成 exe。")
        print("发布包不要提交进 Git，生成后上传到 GitHub Releases。")
        return 0
    if sys.platform != "win32":
        print("请在 Windows 上打包。可以先运行 python build.py --dry-run。")
        return 2
    try:
        import PyInstaller.__main__ as pyinstaller
    except ImportError:
        print("请先安装 PyInstaller: pip install pyinstaller")
        return 2
    for folder in (HERE / "build", DIST):
        if folder.exists():
            shutil.rmtree(folder)
    pyinstaller.run(plan)
    exe = DIST / EXE_NAME
    if not exe.is_file():
        print("打包失败：没有找到 exe")
        return 1
    archive = stage_release(exe)
    print(f"exe: {exe} ({exe.stat().st_size / 1048576:.1f} MB)")
    print(f"发布压缩包: {archive}")
    print("把这个 zip 上传到 GitHub Releases，不要放进仓库。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
