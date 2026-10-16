#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载分类管家
============
监视下载目录，按扩展名把文件整理进分类文件夹。

    python download_manager.py            启动托盘和监控
    python download_manager.py --setup    命令行配置
    python download_manager.py --init     索引已有分类
    python download_manager.py --stats    查看索引
    python download_manager.py 文件或文件夹  整理这些路径后退出
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from dlm import __version__ as VERSION
from dlm.app import App
from dlm.classify import Classifier
from dlm.config import load_config, save_config
from dlm.database import Database, index_existing
from dlm.logging_setup import setup_logging
from dlm.organize import organize_explicit
from dlm.paths import config_path, db_path

log = logging.getLogger("DLM")


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="下载分类管家")
    parser.add_argument("paths", nargs="*", help="整理这些文件或文件夹后退出")
    parser.add_argument("--setup", action="store_true", help="命令行配置向导")
    parser.add_argument("--init", action="store_true", help="索引目标目录里已经分类的文件")
    parser.add_argument("--stats", action="store_true", help="显示索引统计")
    parser.add_argument("--debug", action="store_true", help="输出调试日志")
    parser.add_argument("--version", action="store_true", help="显示版本")
    return parser


def setup_wizard() -> int:
    print("=" * 50)
    print(f"  下载分类管家 v{VERSION}")
    print("=" * 50)
    cfg = load_config()
    current = ",".join(cfg.get("watch_folders") or [])
    try:
        entered = input(f"监控目录，多个用逗号分隔 [{current}]: ").strip()
    except EOFError:
        print("没有控制台输入。请直接运行程序，在托盘里打开设置。")
        return 2
    if entered:
        cfg["watch_folders"] = [part.strip() for part in entered.split(",") if part.strip()]
    default_target = cfg.get("target_base") or (cfg["watch_folders"][0] if cfg["watch_folders"] else "")
    target = input(f"整理目标目录 [{default_target}]: ").strip() or default_target
    cfg["target_base"] = target
    save_config(cfg)
    if target:
        base = Path(target)
        for name in cfg.get("categories") or {}:
            folder = base / name
            folder.mkdir(parents=True, exist_ok=True)
            print(f"  {name}")
    print(f"已保存 {config_path()}")
    return 0


def show_stats(cfg: dict) -> int:
    db = Database(db_path())
    try:
        stats = db.stats()
    finally:
        db.close()
    print(f"索引 {stats['total']} 个文件，其中 {stats['hashed']} 个有指纹")
    for name, count in stats["by_cat"].items():
        print(f"  {name}: {count}")
    if not cfg.get("target_base"):
        print("还没有设置整理目标目录。")
    return 0


def run_init(cfg: dict) -> int:
    target = str(cfg.get("target_base") or "").strip()
    if not target:
        log.error("请先设置整理目标目录")
        return 2
    db = Database(db_path())
    try:
        index_existing(Path(target), cfg.get("categories") or {}, db)
    finally:
        db.close()
    return 0


def run_once(cfg: dict, paths: list[str]) -> int:
    target = str(cfg.get("target_base") or "").strip()
    if not target:
        log.error("请先设置整理目标目录")
        return 2
    classifier = Classifier(cfg.get("categories") or {}, cfg.get("default_category") or "其他")
    result = organize_explicit([Path(item) for item in paths], Path(target), classifier)
    print(f"成功 {result.transferred}，跳过 {result.skipped}，失败 {result.failed}")
    for message in result.errors[:10]:
        print(message)
    return 0 if result.failed == 0 else 1


def already_running() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    ctypes.windll.kernel32.CreateMutexW(None, False, "DownloadManager_v1")
    return ctypes.windll.kernel32.GetLastError() == 183


def tell_already_running() -> None:
    log.error("程序已经在运行。如果看不到窗口，请查看系统托盘。")
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("下载分类管家", "程序已经在运行。\n\n如果看不到窗口，请查看系统托盘。")
        root.destroy()
    except Exception:
        pass


def _open_first_settings(cfg: dict) -> dict:
    try:
        from dlm.settings_window import show_settings_window
    except Exception as exc:
        log.error("无法打开设置窗口: %s", exc)
        return cfg
    show_settings_window(cfg, config_path(), version=VERSION)
    return load_config()


def _console_wait() -> None:
    log.info("按 Ctrl+C 退出")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = _parser().parse_args(argv)
    if args.version:
        print(VERSION)
        return 0
    setup_logging(args.debug)
    log.info("下载分类管家 v%s", VERSION)
    if args.setup:
        return setup_wizard()
    cfg = load_config()
    if args.stats:
        return show_stats(cfg)
    if args.init:
        return run_init(cfg)
    if args.paths:
        return run_once(cfg, args.paths)
    if already_running():
        tell_already_running()
        return 1
    if not cfg.get("watch_folders") or not cfg.get("target_base"):
        log.info("还没有配置监控目录，先打开设置")
        cfg = _open_first_settings(cfg)
    app = App(cfg)
    try:
        app.start()
        try:
            from dlm.tray import setup_tray
        except Exception as exc:
            log.error("托盘模块无法加载: %s", exc)
            _console_wait()
        else:
            if not setup_tray(app):
                _console_wait()
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
