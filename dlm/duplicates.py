"""重复文件处理。默认把新文件挪到「重复文件」，不删除任何已有文件。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from dlm.files import QUARANTINE_DIR_NAME, transfer_into, unique_path
from dlm.fingerprint import smart_fingerprint, usable_fingerprint

log = logging.getLogger("DLM")


@dataclass
class DuplicateResult:
    action: str  # proceed | skip | renamed
    path: Path
    message: str = ""
    open_path: Path | None = None
    existing_fingerprint: str = ""
    new_fingerprint: str = ""


def recycle_file(path: Path) -> bool:
    try:
        from send2trash import send2trash
    except ImportError:
        return False
    try:
        send2trash(str(path))
        return True
    except Exception as exc:
        log.warning("无法移入回收站 %s (%s)", path, exc)
        return False


def _rename_beside(path: Path) -> Path | None:
    try:
        dest = unique_path(path.parent, path.name)
    except (OSError, FileExistsError) as exc:
        log.warning("无法重命名 %s (%s)", path, exc)
        return None
    if dest == path:
        return path
    if transfer(path, dest):
        return dest
    return None


def transfer(path: Path, dest: Path) -> bool:
    from dlm.files import transfer as move

    return move(path, dest, "move")


def resolve_duplicate(
    new_file: Path,
    existing_file: Path,
    *,
    policy: str,
    quarantine_dir: Path,
    stored_hash: str = "",
    ask=None,
    recycle=None,
) -> DuplicateResult:
    """确认内容重复后按策略处理新文件。已有文件始终保留。

    哈希对不上时改名保留两份。隔离失败时也改名，不会退回到直接删除。
    """
    new_file = Path(new_file)
    existing_file = Path(existing_file)
    if not new_file.exists():
        return DuplicateResult("skip", new_file, "新文件已不存在")
    if not existing_file.exists():
        return DuplicateResult("proceed", new_file, "已有记录对应的文件不在了")
    try:
        if existing_file.samefile(new_file):
            return DuplicateResult("proceed", new_file, "是同一个文件")
    except OSError:
        pass
    try:
        new_size = new_file.stat().st_size
        old_size = existing_file.stat().st_size
    except OSError as exc:
        log.warning("无法读取文件大小 (%s)", exc)
        return DuplicateResult("proceed", new_file, "无法比较大小")
    if new_size != old_size:
        return DuplicateResult("proceed", new_file, "大小不同")

    new_fp = smart_fingerprint(new_file)
    old_fp = stored_hash if usable_fingerprint(stored_hash) else ""
    if not old_fp:
        old_fp = smart_fingerprint(existing_file)
    if not new_fp or not old_fp or new_fp != old_fp:
        renamed = _rename_beside(new_file)
        if renamed is None:
            return DuplicateResult("proceed", new_file, "内容不同，保留原名", new_fingerprint=new_fp, existing_fingerprint=old_fp)
        return DuplicateResult(
            "renamed",
            renamed,
            "内容不同，已保留两份",
            open_path=renamed,
            new_fingerprint=new_fp,
            existing_fingerprint=old_fp,
        )

    chosen = policy
    if chosen == "ask":
        answer = "skip"
        if ask is not None:
            try:
                answer = ask(new_file.name, new_file, existing_file)
            except Exception as exc:
                log.warning("重复确认窗口失败，改为隔离 (%s)", exc)
                answer = "skip"
        chosen = "keep" if answer == "keep" else "quarantine"

    if chosen == "keep":
        renamed = _rename_beside(new_file)
        path = renamed or new_file
        return DuplicateResult(
            "renamed" if renamed else "proceed",
            path,
            "已保留副本",
            open_path=path,
            new_fingerprint=new_fp,
            existing_fingerprint=old_fp,
        )

    if chosen == "delete":
        try:
            new_file.unlink()
        except OSError as exc:
            log.warning("彻底删除失败，改为隔离 (%s)", exc)
        else:
            return DuplicateResult(
                "skip",
                new_file,
                "已彻底删除新的重复文件",
                open_path=existing_file,
                new_fingerprint=new_fp,
                existing_fingerprint=old_fp,
            )

    if chosen == "recycle":
        recycler = recycle if recycle is not None else recycle_file
        if recycler(new_file):
            return DuplicateResult(
                "skip",
                new_file,
                "新的重复文件已移入回收站",
                open_path=existing_file,
                new_fingerprint=new_fp,
                existing_fingerprint=old_fp,
            )
        log.warning("回收站不可用，改为移动到「%s」", QUARANTINE_DIR_NAME)

    dest = transfer_into(new_file, quarantine_dir, "move")
    if dest is not None:
        return DuplicateResult(
            "skip",
            dest,
            f"新的重复文件已移动到「{QUARANTINE_DIR_NAME}」",
            open_path=existing_file,
            new_fingerprint=new_fp,
            existing_fingerprint=old_fp,
        )
    renamed = _rename_beside(new_file)
    path = renamed or new_file
    return DuplicateResult(
        "renamed" if renamed else "proceed",
        path,
        "无法隔离重复文件，已改名保留",
        open_path=path,
        new_fingerprint=new_fp,
        existing_fingerprint=old_fp,
    )
