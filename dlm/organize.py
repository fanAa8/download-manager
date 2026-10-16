"""手动和自动整理。智能模式会整夹归类；复制模式保留原文件。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from dlm.classify import (
    ARCHIVE_EXTS,
    INSTALLER_EXTS,
    Classifier,
    folder_has_extension,
    is_app_folder,
)
from dlm.files import (
    QUARANTINE_DIR_NAME,
    contained_in,
    is_reserved_file,
    is_skipped_dir,
    is_temp_file,
    iter_files,
    remove_empty_dirs,
    transfer_into,
)

log = logging.getLogger("DLM")


@dataclass
class OrganizeResult:
    transferred: int = 0
    skipped: int = 0
    failed: int = 0
    skipped_dirs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    moved: list[tuple[str, str]] = field(default_factory=list)

    def __int__(self) -> int:
        return self.transferred

    def __radd__(self, other):
        return int(other) + self.transferred


def _stopped(stop_event) -> bool:
    return stop_event is not None and stop_event.is_set()


def _checkpoint(pause_event, stop_event) -> bool:
    while pause_event is not None and not pause_event.is_set():
        if _stopped(stop_event):
            return False
        pause_event.wait(0.2)
    return not _stopped(stop_event)


def _has_subdirs(folder: Path) -> bool:
    try:
        for child in folder.iterdir():
            if child.is_dir() and not child.is_symlink() and not is_skipped_dir(child):
                return True
    except OSError:
        return False
    return False


def _contains_temp(folder: Path) -> bool:
    for path in iter_files(folder):
        if is_temp_file(path):
            return True
    return False


def _record(result: OrganizeResult, src: Path, directory: Path, mode: str, category: str) -> None:
    dest = transfer_into(src, directory, mode)
    if dest is None:
        result.failed += 1
        result.errors.append(f"无法处理: {src}")
        return
    result.transferred += 1
    result.moved.append((str(dest), category))


class Organizer:
    def __init__(self, classifier: Classifier):
        self.classifier = classifier

    def organize(
        self,
        src: str | Path,
        dst: str | Path,
        mode: str = "smart",
        time_saving: bool = False,
        is_manual: bool = False,
        pause_event=None,
        stop_event=None,
        only_names: set[str] | None = None,
    ) -> OrganizeResult:
        del is_manual  # 手动整理不走监控里的断网暂缓，调用方本来就不会做网络检查。
        result = OrganizeResult()
        src_path, dst_path = Path(src), Path(dst)
        if not src_path.is_dir():
            result.errors.append(f"不是文件夹: {src_path}")
            return result
        transfer_mode = "copy" if mode == "copy" else "move"
        try:
            children = sorted(src_path.iterdir(), key=lambda item: item.name.lower())
        except OSError as exc:
            result.errors.append(str(exc))
            result.failed += 1
            return result

        for item in children:
            if not _checkpoint(pause_event, stop_event):
                break
            if only_names is not None and item.name not in only_names:
                continue
            if item.is_symlink() or is_skipped_dir(item):
                result.skipped += 1
                continue
            if item.is_file():
                self._place_file(item, dst_path, mode, transfer_mode, result, top_level=True)
                continue
            if not item.is_dir():
                continue
            if self._is_output_bucket(item, dst_path):
                result.skipped += 1
                continue
            if contained_in(dst_path, item):
                result.failed += 1
                result.errors.append(f"目标位于源文件夹内部，已跳过: {item.name}")
                continue
            if time_saving and _has_subdirs(item):
                result.skipped += 1
                result.skipped_dirs.append(item.name)
                log.info("省时模式跳过含子目录的文件夹: %s", item.name)
                continue
            if _contains_temp(item):
                result.skipped += 1
                result.skipped_dirs.append(item.name)
                log.info("文件夹里还有未完成文件，暂不整理: %s", item.name)
                continue
            if mode == "smart":
                self._organize_smart(item, dst_path, transfer_mode, result, pause_event, stop_event)
            else:
                self._organize_flat(item, dst_path, transfer_mode, result, pause_event, stop_event)
            if transfer_mode == "move":
                remove_empty_dirs(item, preserve=src_path)
        if mode == "smart" and transfer_mode == "move":
            # 散文件搬走后，空的中间目录一并清掉；监控根目录本身保留。
            pass
        log.info(
            "整理结束: 成功 %s，跳过 %s，失败 %s",
            result.transferred,
            result.skipped,
            result.failed,
        )
        return result

    def _is_output_bucket(self, item: Path, dst: Path) -> bool:
        if item.name == QUARANTINE_DIR_NAME:
            return True
        if item.name not in self.classifier.category_names():
            return False
        try:
            return item.resolve() == (dst / item.name).resolve()
        except OSError:
            return False

    def _place_file(self, path: Path, dst: Path, mode: str, transfer_mode: str, result: OrganizeResult, top_level: bool) -> None:
        if is_temp_file(path) or path.is_symlink():
            result.skipped += 1
            return
        if top_level and is_reserved_file(path):
            result.skipped += 1
            return
        category = self.classifier.classify(path.name)
        if mode == "smart" and category == self.classifier.default_cat:
            result.skipped += 1
            return
        before = result.transferred
        _record(result, path, dst / category, transfer_mode, category)
        if result.transferred > before:
            log.info("已归档 %s → %s/", path.name, category)

    def _place_tree(self, folder: Path, dest_root: Path, transfer_mode: str, result: OrganizeResult, pause_event, stop_event) -> None:
        for path in list(iter_files(folder)):
            if not _checkpoint(pause_event, stop_event):
                return
            if is_temp_file(path):
                result.skipped += 1
                continue
            relative = path.relative_to(folder)
            category = dest_root.parent.name
            before = result.transferred
            _record(result, path, dest_root / relative.parent, transfer_mode, category)
            if result.transferred > before:
                log.info("已归档 %s → %s/", path.name, category)

    def _organize_flat(self, folder, dst, transfer_mode, result, pause_event, stop_event) -> None:
        for path in list(iter_files(folder)):
            if not _checkpoint(pause_event, stop_event):
                return
            if is_temp_file(path):
                result.skipped += 1
                continue
            category = self.classifier.classify(path.name)
            relative = path.relative_to(folder)
            before = result.transferred
            _record(
                result,
                path,
                dst / category / folder.name / relative.parent,
                transfer_mode,
                category,
            )
            if result.transferred > before:
                log.info("已归档 %s → %s/%s/", path.name, category, folder.name)

    def _organize_smart(self, folder, dst, transfer_mode, result, pause_event, stop_event) -> None:
        if is_app_folder(folder):
            result.skipped += 1
            result.skipped_dirs.append(folder.name)
            log.info("跳过应用程序目录: %s", folder.name)
            return
        counts: dict[str, int] = {}
        total_files = 0
        for path in iter_files(folder):
            if is_temp_file(path):
                continue
            total_files += 1
            category = self.classifier.classify(path.name)
            counts[category] = counts.get(category, 0) + 1
        if total_files == 0:
            result.skipped += 1
            return
        useful = {
            name: count
            for name, count in counts.items()
            if name != self.classifier.default_cat
        }
        useful_total = sum(useful.values())
        if not useful:
            result.skipped += 1
            return
        dominant = max(useful, key=useful.get)
        ratio = useful[dominant] / useful_total
        kinds = len(useful)

        if kinds == 1 or (kinds == 2 and ratio >= 0.7):
            self._place_tree(folder, dst / dominant / folder.name, transfer_mode, result, pause_event, stop_event)
            return
        if kinds == 2:
            names = list(useful)
            winner = self.classifier.correlation_winner(names[0], names[1])
            if winner:
                self._place_tree(folder, dst / winner / folder.name, transfer_mode, result, pause_event, stop_event)
                return
        if kinds >= 3 and _is_installer_bundle(folder):
            archive = self.classifier.category_for_role("archive", "压缩包")
            self._place_tree(folder, dst / archive / folder.name, transfer_mode, result, pause_event, stop_event)
            return
        # 没有任何一类达到一半时全部平铺；否则多数派保留文件夹名。
        inherit = ratio >= 0.5
        for path in list(iter_files(folder)):
            if not _checkpoint(pause_event, stop_event):
                return
            if is_temp_file(path):
                result.skipped += 1
                continue
            category = self.classifier.classify(path.name)
            if category == self.classifier.default_cat:
                result.skipped += 1
                continue
            relative = path.relative_to(folder)
            if inherit and category == dominant:
                directory = dst / category / folder.name / relative.parent
            else:
                directory = dst / category
            before = result.transferred
            _record(result, path, directory, transfer_mode, category)
            if result.transferred > before:
                log.info("已归档 %s → %s/", path.name, category)


def _is_installer_bundle(folder: Path) -> bool:
    return folder_has_extension(folder, INSTALLER_EXTS) and folder_has_extension(folder, ARCHIVE_EXTS)


def organize_explicit(paths: list[Path], target: Path, classifier: Classifier) -> OrganizeResult:
    """发送到 / 命令行传入的路径。文件直接归档，文件夹按智能模式处理。"""
    total = OrganizeResult()
    organizer = Organizer(classifier)
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            total.failed += 1
            total.errors.append(f"不存在: {path}")
            continue
        if path.is_file():
            if is_temp_file(path):
                total.skipped += 1
                continue
            category = classifier.classify(path.name)
            if category == classifier.default_cat:
                category = classifier.default_cat
            dest = transfer_into(path, target / category, "move")
            if dest is None:
                total.failed += 1
                total.errors.append(f"无法处理: {path}")
            else:
                total.transferred += 1
                log.info("已归档 %s → %s/", path.name, category)
            continue
        part = organizer.organize(path.parent, target, mode="smart", only_names={path.name})
        total.transferred += part.transferred
        total.skipped += part.skipped
        total.failed += part.failed
        total.skipped_dirs.extend(part.skipped_dirs)
        total.errors.extend(part.errors)
    return total
