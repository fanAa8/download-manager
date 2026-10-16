"""监控进程的生命周期：配置热更新、目录监视和退出清理。"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from dlm.classify import Classifier
from dlm.database import Database, index_existing
from dlm.organize import Organizer
from dlm.paths import db_path
from dlm.runtime import RUNTIME
from dlm.watcher import DownloadHandler

log = logging.getLogger("DLM")


class App:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.db = Database(db_path())
        self.classifier = Classifier(cfg.get("categories") or {}, cfg.get("default_category") or "其他")
        self.handler = DownloadHandler(self.db, self.classifier, self.cfg)
        self.observer = None
        self.started = False
        self._stopped = False
        RUNTIME.app = self

    def apply_config(self, cfg: dict) -> None:
        self.cfg.clear()
        self.cfg.update(cfg)
        self.classifier.reconfigure(
            self.cfg.get("categories") or {},
            self.cfg.get("default_category") or "其他",
        )
        self.handler.config = self.cfg
        self.handler.classifier = self.classifier
        self.handler.organizer = Organizer(self.classifier)
        self.handler.refresh_limits()
        for ext, kept, ignored in self.classifier.conflicts:
            log.warning("扩展名 %s 同时属于「%s」和「%s」，按「%s」处理", ext, kept, ignored, kept)
        self.reschedule()

    def reschedule(self) -> None:
        if not self._ensure_observer():
            return
        try:
            self.observer.unschedule_all()
        except Exception as exc:
            log.warning("取消监控失败 (%s)", exc)
        scheduled = 0
        for folder in self.cfg.get("watch_folders") or []:
            if os.path.isdir(folder):
                self.observer.schedule(self.handler, folder, recursive=True)
                log.info("监控: %s", folder)
                scheduled += 1
            else:
                log.warning("目录不存在: %s", folder)
        self.handler.start_loops()
        if scheduled and not self.started:
            self.observer.start()
            self.started = True
        elif not scheduled:
            log.info("没有可监控的目录。打开托盘菜单里的设置后即可开始。")

    def start(self) -> None:
        target = str(self.cfg.get("target_base") or "").strip()
        categories = self.cfg.get("categories") or {}
        if target:
            def _scan() -> None:
                try:
                    index_existing(Path(target), categories, self.db)
                except Exception:
                    log.exception("初始扫描失败")

            threading.Thread(target=_scan, name="dlm-scan", daemon=True).start()
        for ext, kept, ignored in self.classifier.conflicts:
            log.warning("扩展名 %s 同时属于「%s」和「%s」，按「%s」处理", ext, kept, ignored, kept)
        policy = self.cfg.get("duplicate_action", "quarantine")
        log.info("重复文件策略: %s", policy)
        self.reschedule()

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        log.info("正在退出")
        try:
            self.handler.stop_loops()
        except Exception:
            log.exception("停止处理线程失败")
        if self.observer is not None and self.started:
            try:
                self.observer.stop()
                self.observer.join(timeout=5)
            except Exception:
                log.exception("停止监控失败")
        try:
            self.db.close()
        except Exception:
            pass
        log.info("已退出")

    def _ensure_observer(self) -> bool:
        if self.observer is not None:
            return True
        try:
            from watchdog.observers import Observer
        except ImportError:
            log.error("请安装 watchdog: pip install watchdog")
            return False
        self.observer = Observer()
        return True
