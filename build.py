#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build standalone exe for Download Manager.
Run:  python build.py

Output: dist\下载分类管家.exe  (single-file, portable)
"""

import os, shutil, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent   # .../download-manager/
OUT_DIR = HERE              # output exe directly to project root
EXE_NAME = "下载分类管家.exe"

# ── Paths ──
main_py     = HERE / "download_manager.py"
config_json = HERE / "config.json"
install_bat = HERE / "install.bat"
if not main_py.exists():
    print(f"ERROR: {main_py} not found")
    sys.exit(1)

print("=" * 50)
print("  下载分类管家 — PyInstaller 打包")
print("=" * 50)
print(f"  Source : {main_py.name}")
print(f"  Config : {config_json.name}")
print(f"  Output : {OUT_DIR / EXE_NAME}  (project root)")
print()

# ── Clean old build artifacts (never delete root/source) ──
for d in [HERE / "build", HERE / "build_temp", HERE / "dist"]:
    if d.exists():
        shutil.rmtree(d)
        print(f"  Cleaned: {d}")
old_exe = HERE / EXE_NAME
if old_exe.exists():
    old_exe.unlink()
    print(f"  Cleaned: {old_exe.name}")

# ── Windows --add-data separator is ';' (not ':') ──
add_data_sep = ";"   # Windows

PyInstaller_args = [
    str(main_py),
    "--name", EXE_NAME.replace(".exe", ""),
    "--onefile",
    "--windowed",    # no console window (use --console for debug)
    "--clean",
    "--noconfirm",
    "--distpath", str(OUT_DIR),
    "--add-data", f"{config_json}{add_data_sep}.",
]

# ── If install.bat exists, bundle it too ──
if install_bat.exists():
    PyInstaller_args += ["--add-data", f"{install_bat}{add_data_sep}."]
    print(f"  + Bundle: {install_bat.name}")

# ── Hidden imports ──
hidden = [
    "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
    "watchdog", "watchdog.observers", "watchdog.events",
    "sqlite3",
    "winreg", "ctypes", "ctypes.wintypes",
    "settings_ui",
    "pystray", "pystray._win32",
    "PIL", "PIL.Image", "PIL.ImageDraw",
]
for mod in hidden:
    PyInstaller_args += ["--hidden-import", mod]

# ── Exclude heavy unused modules ──
exclude = ["matplotlib", "numpy", "pandas", "scipy"]
for mod in exclude:
    PyInstaller_args += ["--exclude-module", mod]

print(f"  -> PyInstaller args: {len(PyInstaller_args)} items")
print(f"  -> Building... (30-90s, watch for errors below)")
print()

# ── Run PyInstaller ──
import PyInstaller.__main__
try:
    PyInstaller.__main__.run(PyInstaller_args)
except SystemExit as e:
    if e.code not in (0, None):
        print(f"\nERROR: PyInstaller exited with code {e.code}")
        sys.exit(e.code)

# ── Check result ──
exe = OUT_DIR / EXE_NAME
if exe.exists():
    size_mb = exe.stat().st_size / (1024 * 1024)
    print()
    print("=" * 50)
    print(f"  [OK]  Build success!")
    print(f"  [EXE]  {exe}")
    print(f"  [SIZE] {size_mb:.1f} MB")
    print()
    print("  Usage:")
    print(f"      - Double-click {EXE_NAME} to start")
    print(f"      - Or run from cmd:  {exe}")
    print(f"      - Config is embedded; first run extracts config.json")
    print("=" * 50)
else:
    print("\nERROR: Build failed — exe not found")
    sys.exit(1)