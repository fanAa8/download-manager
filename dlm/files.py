"""文件名、搬运和空目录清理。只移动或复制，不覆盖已有文件。"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

log = logging.getLogger("DLM")

QUARANTINE_DIR_NAME = "重复文件"

TEMP_SUFFIXES = {
    ".crdownload",
    ".part",
    ".partial",
    ".tmp",
    ".temp",
    ".download",
    ".dl",
    ".bc!",
    ".opdownload",
    ".aria2",
    ".td",
    ".xltd",
    ".!ut",
    ".!qb",
    ".filepart",
    ".fdmdownload",
    ".downloading",
}

RESERVED_FILE_NAMES = {
    "config.json",
    "config.default.json",
    "config.json.tmp",
    "download_manager.log",
    "download_manager.db",
    "download_manager.db-wal",
    "download_manager.db-shm",
    "desktop.ini",
    "thumbs.db",
}

SKIP_DIR_NAMES = {
    "$recycle.bin",
    "system volume information",
    "config.msi",
    ".git",
    "__pycache__",
}


def is_temp_file(path: Path) -> bool:
    """下载器还没写完的临时文件。这类文件不能归档。"""
    name = path.name.lower()
    if not name or name in {".", ".."}:
        return True
    if name.startswith(".") or name.startswith("~$") or name.startswith("~"):
        return True
    if name.endswith(".baiduyun.p.downloading") or name.endswith(".td.cfg"):
        return True
    suffix = path.suffix.lower()
    if suffix in TEMP_SUFFIXES:
        return True
    return False


def is_reserved_file(path: Path) -> bool:
    return path.name.lower() in RESERVED_FILE_NAMES


def is_skipped_dir(path: Path) -> bool:
    return path.name.lower() in SKIP_DIR_NAMES or path.name == QUARANTINE_DIR_NAME


def file_available(path: Path) -> bool:
    """文件能读取，且在 Windows 上没有被下载器独占。"""
    if not path.is_file() or is_temp_file(path):
        return False
    try:
        with open(path, "rb") as handle:
            handle.read(1)
    except OSError:
        return False
    if sys.platform == "win32":
        try:
            os.rename(path, path)
        except OSError:
            return False
    return True


def iter_files(folder: Path, limit: int | None = None):
    """不跟随符号链接地遍历文件。"""
    if not folder.is_dir():
        return
    seen = 0
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if not is_skipped_dir(current / name)
            and not (current / name).is_symlink()
        ]
        for name in filenames:
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            yield path
            seen += 1
            if limit is not None and seen >= limit:
                return


def unique_path(directory: Path, filename: str) -> Path:
    """在目录中找一个还不存在的文件名。已有同名文件时追加 (2)、(3)。"""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for index in range(2, 500):
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"重名过多: {filename}")


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return os.path.abspath(str(left)) == os.path.abspath(str(right))


def transfer(src: Path, dest: Path, mode: str) -> bool:
    """把 src 复制或移动到一个尚不存在的 dest。失败时原文件保留。"""
    src = Path(src)
    dest = Path(dest)
    if not src.exists() or src.is_symlink():
        return False
    if _same_path(src, dest):
        return True
    if dest.exists():
        log.warning("目标已存在，取消覆盖: %s", dest)
        return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("无法创建目录 %s (%s)", dest.parent, exc)
        return False
    try:
        if mode == "copy":
            shutil.copy2(str(src), str(dest))
        else:
            shutil.move(str(src), str(dest))
    except OSError as exc:
        log.warning("搬运失败: %s -> %s (%s)", src, dest, exc)
        return False
    if not dest.exists():
        log.warning("搬运后目标不存在: %s", dest)
        return False
    if mode != "copy" and src.exists():
        log.warning("已复制到目标，但原文件仍保留: %s", src)
    return True


def transfer_into(src: Path, directory: Path, mode: str) -> Path | None:
    """放入目录并自动避开重名。返回最终路径；失败返回 None，不删除源文件。"""
    src = Path(src)
    if not src.exists():
        return None
    for _ in range(5):
        try:
            dest = unique_path(directory, src.name)
        except (OSError, FileExistsError) as exc:
            log.warning("无法分配文件名 %s (%s)", src.name, exc)
            return None
        if transfer(src, dest, mode):
            return dest
        if not src.exists():
            return dest if dest.exists() else None
    return None


def remove_empty_dirs(root: Path, preserve: Path | None = None) -> None:
    """自底向上删除空目录。不删除 preserve，也不删除仍有内容的目录。"""
    if not root.is_dir() or root.is_symlink():
        return
    preserve_key = None
    if preserve is not None:
        try:
            preserve_key = str(preserve.resolve())
        except OSError:
            preserve_key = os.path.abspath(str(preserve))
    for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        if filenames or dirnames:
            # 子目录可能已经删掉，再确认一次是否真的空。
            pass
        current = Path(dirpath)
        if current.is_symlink():
            continue
        try:
            current_key = str(current.resolve())
        except OSError:
            current_key = os.path.abspath(str(current))
        if preserve_key is not None and current_key == preserve_key:
            continue
        try:
            next(current.iterdir())
        except StopIteration:
            try:
                current.rmdir()
            except OSError:
                pass
        except OSError:
            pass


def contained_in(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False
