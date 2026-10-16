"""判断新文件有没有下完，以及它该走单文件还是整夹流程。"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from dlm.files import (
    QUARANTINE_DIR_NAME,
    SKIP_DIR_NAMES,
    file_available,
    is_reserved_file,
    is_temp_file,
    iter_files,
)

log = logging.getLogger("DLM")


@dataclass
class FolderScan:
    size: int = 0
    files: int = 0
    temp_files: int = 0
    locked: bool = False
    unreadable: bool = False
    missing: bool = False

    @property
    def settled(self) -> bool:
        return (
            not self.missing
            and not self.unreadable
            and not self.locked
            and self.temp_files == 0
            and self.files > 0
            and self.size > 0
        )


def scan_folder(folder: Path) -> FolderScan:
    """统计文件夹体积、临时文件和是否仍被占用。"""
    scan = FolderScan()
    if not folder.exists():
        scan.missing = True
        return scan
    if not folder.is_dir():
        scan.unreadable = True
        return scan
    try:
        for path in iter_files(folder):
            if is_temp_file(path):
                scan.temp_files += 1
                try:
                    scan.size += path.stat().st_size
                except OSError:
                    scan.locked = True
                continue
            scan.files += 1
            try:
                scan.size += path.stat().st_size
            except OSError:
                scan.locked = True
                continue
            if not file_available(path):
                scan.locked = True
    except OSError:
        scan.unreadable = True
    return scan


@dataclass
class Probe:
    exists: bool
    size: int = 0
    settled: bool = False


@dataclass
class Stability:
    """连续若干次体积不变且已释放，才算下载完成。体积仍在变化时顺延截止时间。"""

    needed_hits: int
    max_wait: float
    last_size: int = -1
    hits: int = 0
    deadline: float = 0

    def observe(self, now: float, size: int, settled: bool) -> str:
        if not settled or size <= 0 or size != self.last_size:
            if size != self.last_size and self.last_size != -1:
                self.deadline = now + self.max_wait
            self.last_size = size
            self.hits = 0
            if now >= self.deadline:
                return "give_up"
            return "wait"
        self.hits += 1
        self.last_size = size
        if self.hits >= self.needed_hits:
            return "ready"
        if now >= self.deadline:
            return "give_up"
        return "wait"


@dataclass
class Tracked:
    kind: str
    path: Path
    stability: Stability
    quiet_until: float = 0
    not_before: float = 0
    attempts: int = 0
    max_attempts: int = 3
    retry_delay: float = 30
    offline_since: float | None = None
    key: str = ""


def path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _abs(path: Path) -> Path:
    return Path(os.path.abspath(str(path)))


def event_action(
    path: Path,
    is_directory: bool,
    watch_roots: list[Path],
    category_names: set[str],
    target: Path | None,
) -> tuple[str, Path | None]:
    """返回 ('ignore', None)、('file', 文件) 或 ('folder', 顶层文件夹)。

    监控根目录里的散文件单独归档。子目录里的新文件不拆出来，等整个顶层文件夹下完。
    已经在目标分类目录或「重复文件」里的路径忽略，避免搬进去后又被搬走。
    """
    current = _abs(path)
    protected = set(category_names) | {QUARANTINE_DIR_NAME}
    if target is not None:
        try:
            relative = current.relative_to(_abs(target))
        except ValueError:
            relative = None
        if relative is not None and relative.parts and relative.parts[0] in protected:
            return "ignore", None

    match: tuple[Path, Path] | None = None
    for root in watch_roots:
        root_abs = _abs(root)
        try:
            relative = current.relative_to(root_abs)
        except ValueError:
            continue
        if match is None or len(root_abs.parts) > len(match[0].parts):
            match = (root_abs, relative)
    if match is None or not match[1].parts:
        return "ignore", None
    root_abs, relative = match
    top_name = relative.parts[0]
    if top_name.lower() in SKIP_DIR_NAMES or top_name == QUARANTINE_DIR_NAME:
        return "ignore", None
    top = root_abs / top_name
    if len(relative.parts) == 1:
        if is_directory:
            return "folder", top
        if is_temp_file(current) or is_reserved_file(current):
            return "ignore", None
        return "file", current
    return "folder", top


class ArrivalQueue:
    """监视新路径，直到稳定、放弃或消失。探测放在锁外，避免卡住文件系统事件。"""

    def __init__(
        self,
        settle_window: float = 3,
        file_hits: int = 2,
        file_max_wait: float = 1800,
        folder_hits: int = 2,
        folder_initial_delay: float = 15,
        folder_max_wait: float = 300,
        max_attempts: int = 3,
        retry_delay: float = 30,
        offline_threshold: int = 0,
        offline_hold: float = 0,
        net_ok=None,
    ):
        self.settle_window = settle_window
        self.file_hits = file_hits
        self.file_max_wait = file_max_wait
        self.folder_hits = folder_hits
        self.folder_initial_delay = folder_initial_delay
        self.folder_max_wait = folder_max_wait
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay
        self.offline_threshold = offline_threshold
        self.offline_hold = offline_hold
        self.net_ok = net_ok or (lambda: True)
        self.tracked: dict[str, Tracked] = {}
        self.lock = threading.Lock()

    def watch(self, kind: str, path: Path, now: float) -> None:
        key = path_key(path)
        with self.lock:
            item = self.tracked.get(key)
            if item is None:
                max_wait = self.folder_max_wait if kind == "folder" else self.file_max_wait
                hits = self.folder_hits if kind == "folder" else self.file_hits
                initial = self.folder_initial_delay if kind == "folder" else 0
                item = Tracked(
                    kind=kind,
                    path=Path(path),
                    stability=Stability(needed_hits=max(1, hits), max_wait=max_wait, deadline=now + max_wait),
                    not_before=now + initial,
                    max_attempts=self.max_attempts,
                    retry_delay=self.retry_delay,
                    key=key,
                )
                self.tracked[key] = item
            item.quiet_until = max(item.quiet_until, now + self.settle_window)
            item.stability.deadline = max(
                item.stability.deadline, now + item.stability.max_wait
            )

    def postpone(self, now: float) -> None:
        """暂停期间不把等待中的文件判为超时。"""
        with self.lock:
            for item in self.tracked.values():
                item.stability.deadline = max(item.stability.deadline, now + item.stability.max_wait)
                item.quiet_until = max(item.quiet_until, now + 1)

    def poll(self, now: float, probe_fn) -> tuple[list[Tracked], list[Tracked]]:
        with self.lock:
            items = list(self.tracked.values())
        probed: list[tuple[Tracked, Probe | None]] = []
        for item in items:
            if now < item.quiet_until or now < item.not_before:
                probed.append((item, None))
                continue
            try:
                probe = probe_fn(item)
            except Exception as exc:
                log.debug("探测失败 %s: %s", item.path, exc)
                probe = Probe(exists=True, size=0, settled=False)
            probed.append((item, probe))

        ready: list[Tracked] = []
        abandoned: list[Tracked] = []
        with self.lock:
            for item, probe in probed:
                current = self.tracked.get(item.key)
                if current is None or current is not item:
                    continue
                if probe is None:
                    continue
                if not probe.exists:
                    self.tracked.pop(item.key, None)
                    continue
                if probe.size != item.stability.last_size and item.stability.last_size != -1:
                    item.offline_since = None
                decision = item.stability.observe(now, probe.size, probe.settled)
                if (
                    decision == "ready"
                    and self.offline_threshold > 0
                    and probe.size >= self.offline_threshold
                    and not self.net_ok()
                ):
                    if item.offline_since is None:
                        item.offline_since = now
                        log.warning("网络不可用，大文件暂缓移动: %s", item.path)
                    if now - item.offline_since < self.offline_hold:
                        item.stability.deadline = max(
                            item.stability.deadline, now + item.stability.max_wait
                        )
                        continue
                if decision == "ready":
                    self.tracked.pop(item.key, None)
                    ready.append(item)
                    continue
                if decision == "give_up":
                    item.attempts += 1
                    if item.attempts <= item.max_attempts:
                        item.stability.hits = 0
                        item.stability.last_size = -1
                        item.stability.deadline = now + item.retry_delay + item.stability.max_wait
                        item.quiet_until = now + item.retry_delay
                        item.offline_since = None
                        log.info("尚未完成，稍后重试 (%s/%s): %s", item.attempts, item.max_attempts, item.path)
                        continue
                    self.tracked.pop(item.key, None)
                    abandoned.append(item)
        return ready, abandoned


def is_internet_available(timeout: float = 1.0) -> bool:
    """轻量连通性检查。失败只表示先别搬大文件，不代表文件一定没下完。"""
    for host in ("223.5.5.5", "1.1.1.1"):
        try:
            socket.create_connection((host, 53), timeout=timeout)
            return True
        except OSError:
            continue
    return False


class NetCache:
    def __init__(self, ttl: float = 30):
        self.ttl = ttl
        self.checked_at = 0.0
        self.ok = True
        self.lock = threading.Lock()

    def ok_now(self, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        with self.lock:
            if moment - self.checked_at < self.ttl:
                return self.ok
        result = is_internet_available()
        with self.lock:
            self.checked_at = moment
            self.ok = result
            return result
