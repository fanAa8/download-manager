"""监控下载目录。完成判定在后台轮询，真正搬文件的只有一个线程。"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from pathlib import Path

from dlm.classify import Classifier
from dlm.database import Database
from dlm.duplicates import resolve_duplicate
from dlm.files import QUARANTINE_DIR_NAME, file_available, is_temp_file, transfer_into
from dlm.fingerprint import HASH_THRESHOLD
from dlm.organize import Organizer
from dlm.readiness import ArrivalQueue, NetCache, Probe, Tracked, event_action, path_key, scan_folder

log = logging.getLogger("DLM")

try:
    from watchdog.events import FileSystemEventHandler as _WatchdogHandler
except ImportError:  # 测试和 --help 不需要真正监视文件系统
    class _WatchdogHandler:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            pass


class DownloadHandler(_WatchdogHandler):
    def __init__(self, db: Database, classifier: Classifier, config: dict):
        super().__init__()
        self.db = db
        self.classifier = classifier
        self.config = config
        self.organizer = Organizer(classifier)
        self.stop = threading.Event()
        self.paused = threading.Event()
        self.user_paused = False
        self._manual_depth = 0
        self._pause_lock = threading.Lock()
        self.jobs: queue.Queue = queue.Queue()
        self._fails: dict[str, int] = {}
        self._toast_lock = threading.Lock()
        self._toast_batch: list[tuple[str, str, Path | None]] = []
        self._toast_timer: threading.Timer | None = None
        self.net = NetCache()
        self.poll_interval = 2
        self.queue = ArrivalQueue(net_ok=self.net.ok_now)
        self._loops_started = False
        self._poller: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self.refresh_limits()

    def refresh_limits(self) -> None:
        cfg = self.config
        interval = max(1, int(cfg.get("poll_interval", 2)))
        self.poll_interval = interval
        self.queue.settle_window = float(cfg.get("settle_window", 3))
        self.queue.file_hits = max(2, math.ceil(int(cfg.get("download_complete_wait", 5)) / interval))
        self.queue.file_max_wait = float(cfg.get("file_max_wait", 1800))
        self.queue.folder_hits = 2
        self.queue.folder_initial_delay = float(cfg.get("batch_window", 15))
        self.queue.folder_max_wait = float(cfg.get("batch_max_wait", 300))
        hold = float(cfg.get("offline_hold_seconds", 600))
        self.queue.offline_hold = hold
        self.queue.offline_threshold = HASH_THRESHOLD if hold > 0 else 0

    def target_path(self) -> Path | None:
        raw = str(self.config.get("target_base") or "").strip()
        return Path(raw) if raw else None

    def watch_roots(self) -> list[Path]:
        return [Path(item) for item in self.config.get("watch_folders") or [] if str(item).strip()]

    def set_user_paused(self, paused: bool) -> None:
        with self._pause_lock:
            self.user_paused = paused
            self._sync_pause()

    def toggle_user_paused(self) -> bool:
        with self._pause_lock:
            self.user_paused = not self.user_paused
            self._sync_pause()
            return self.user_paused

    def push_manual(self) -> None:
        with self._pause_lock:
            self._manual_depth += 1
            self._sync_pause()

    def pop_manual(self) -> None:
        with self._pause_lock:
            self._manual_depth = max(0, self._manual_depth - 1)
            self._sync_pause()

    def _sync_pause(self) -> None:
        if self.user_paused or self._manual_depth:
            self.paused.set()
        else:
            self.paused.clear()

    def start_loops(self) -> None:
        if self._loops_started:
            return
        self._loops_started = True
        self._poller = threading.Thread(target=self._poll_loop, name="dlm-poll", daemon=True)
        self._worker = threading.Thread(target=self._work_loop, name="dlm-move", daemon=True)
        self._poller.start()
        self._worker.start()

    def stop_loops(self) -> None:
        self.stop.set()
        self.jobs.put(None)
        if self._poller is not None:
            self._poller.join(timeout=2)
        if self._worker is not None:
            self._worker.join(timeout=2)

    def on_created(self, event) -> None:
        self._note(Path(event.src_path), bool(event.is_directory))

    def on_moved(self, event) -> None:
        self._note(Path(event.dest_path), bool(event.is_directory))

    def on_modified(self, event) -> None:
        if event.is_directory:
            return
        self._note(Path(event.src_path), False)

    def _note(self, path: Path, is_directory: bool) -> None:
        if self.stop.is_set():
            return
        kind, target = event_action(
            path,
            is_directory,
            self.watch_roots(),
            self.classifier.category_names(),
            self.target_path(),
        )
        if kind == "ignore" or target is None:
            return
        self.queue.watch(kind, target, time.monotonic())
        log.debug("等待完成: %s (%s)", target, kind)

    def _poll_loop(self) -> None:
        while not self.stop.wait(self.poll_interval):
            now = time.monotonic()
            if self.paused.is_set():
                self.queue.postpone(now)
                continue
            ready, abandoned = self.queue.poll(now, self._probe)
            for item in ready:
                self.jobs.put(item)
            for item in abandoned:
                log.warning("仍未完成，文件留在原处: %s", item.path)
                self._announce("仍未完成", f"{item.path.name} 留在原处", item.path)

    def _probe(self, item: Tracked) -> Probe:
        path = item.path
        if not path.exists():
            return Probe(False)
        if item.kind == "folder":
            scan = scan_folder(path)
            if scan.missing:
                return Probe(False)
            return Probe(True, scan.size, scan.settled)
        try:
            size = path.stat().st_size
        except OSError:
            return Probe(True, 0, False)
        settled = size > 0 and file_available(path) and not is_temp_file(path)
        return Probe(True, size, settled)

    def _work_loop(self) -> None:
        while True:
            item = self.jobs.get()
            try:
                if item is None or self.stop.is_set():
                    return
                if self.paused.is_set():
                    self.queue.watch(item.kind, item.path, time.monotonic())
                    continue
                if item.kind == "folder":
                    self._process_folder(item.path)
                else:
                    self._process_file(item.path)
            except Exception:
                log.exception("处理失败: %s", getattr(item, "path", item))
            finally:
                self.jobs.task_done()

    def _defer(self, kind: str, path: Path) -> None:
        key = path_key(path)
        self._fails[key] = self._fails.get(key, 0) + 1
        if self._fails[key] >= 5:
            log.warning("多次确认仍未完成，停止自动处理: %s", path)
            return
        self.queue.watch(kind, path, time.monotonic())

    def _process_file(self, fp: Path) -> None:
        if not fp.exists() or not fp.is_file() or is_temp_file(fp):
            return
        if not file_available(fp):
            self._defer("file", fp)
            return
        try:
            size = fp.stat().st_size
        except OSError as exc:
            log.warning("无法读取 %s (%s)", fp, exc)
            return
        if size <= 0:
            self._defer("file", fp)
            return
        target = self.target_path()
        if target is None:
            log.warning("还没有设置整理目标目录")
            return
        outcome = self._duplicate(fp, size, target)
        if outcome is None:
            return
        fp = outcome
        category = self.classifier.classify(fp.name)
        try:
            info_size = fp.stat().st_size
        except OSError:
            return
        dest = transfer_into(fp, target / category, "move")
        if dest is None or not dest.exists():
            log.error("移动失败，原文件保留: %s", fp.name)
            return
        self._fails.pop(path_key(fp), None)
        self.db.add_file("", dest.name, info_size, str(dest), category)
        log.info("已移动: %s → %s/", dest.name, category)
        self._announce("文件已分类", f"{dest.name} → {category}", dest)

    def _duplicate(self, fp: Path, size: int, target: Path) -> Path | None:
        existing = self.db.find_live(fp.name, size)
        if not existing:
            return fp
        policy = str(self.config.get("duplicate_action") or "quarantine")
        result = resolve_duplicate(
            fp,
            Path(existing["path"]),
            policy=policy,
            quarantine_dir=target / QUARANTINE_DIR_NAME,
            stored_hash=existing.get("hash") or "",
            ask=self._ask_duplicate if policy == "ask" else None,
        )
        if result.existing_fingerprint:
            self.db.update_hash(existing["path"], result.existing_fingerprint)
        log.info("重复检查 %s: %s", fp.name, result.message)
        if result.action == "skip":
            self._announce("重复文件", result.message, result.open_path)
            return None
        if result.action == "renamed":
            self._announce("保留两份", result.message, result.path)
            return result.path
        return fp

    def _ask_duplicate(self, name: str, new_path: Path, existing: Path) -> str:
        from dlm.dialogs import dup_dialog

        choice = dup_dialog(name, new_path, {"path": str(existing), "size": new_path.stat().st_size, "category": ""})
        return "keep" if choice == "keep" else "skip"

    def _process_folder(self, folder: Path) -> None:
        if not folder.is_dir():
            return
        target = self.target_path()
        if target is None:
            log.warning("还没有设置整理目标目录")
            return
        result = self.organizer.organize(
            folder.parent,
            target,
            mode="smart",
            only_names={folder.name},
        )
        for moved, category in result.moved:
            path = Path(moved)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            self.db.add_file("", path.name, size, str(path), category)
        if result.transferred:
            self._announce(
                "文件夹已分类",
                f"{folder.name}：{result.transferred} 个文件",
                target,
            )
            log.info("文件夹已整理: %s (%s 个文件)", folder.name, result.transferred)
        elif result.skipped_dirs:
            log.info("跳过文件夹: %s", folder.name)
        elif result.failed:
            log.warning("文件夹整理失败 %s: %s", folder.name, "；".join(result.errors[:5]))

    def _announce(self, title: str, message: str, path: Path | None) -> None:
        with self._toast_lock:
            self._toast_batch.append((title, message, path))
            if self._toast_timer is not None:
                self._toast_timer.cancel()
            timer = threading.Timer(1.2, self._flush_toast)
            timer.daemon = True
            self._toast_timer = timer
            timer.start()

    def _flush_toast(self) -> None:
        with self._toast_lock:
            batch = self._toast_batch
            self._toast_batch = []
            self._toast_timer = None
        if not batch:
            return
        from dlm.notify import open_file_location, show_toast

        if len(batch) == 1:
            title, message, path = batch[0]
        else:
            title = f"已整理 {len(batch)} 项"
            message = batch[-1][1]
            path = batch[-1][2]
        callback = None
        if path is not None:
            callback = lambda target=path: open_file_location(target)
        show_toast(title, message, click_callback=callback)
