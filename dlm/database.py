"""已归档文件索引，用来识别同名同大小的重复项。"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

log = logging.getLogger("DLM")

_COLUMNS = ("hash", "name", "size", "path", "category")


class Database:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=5, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.RLock()
        self._init()

    def _init(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_hash TEXT DEFAULT '',
                    file_name TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    category TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_hash ON files(file_hash);
                CREATE INDEX IF NOT EXISTS idx_name ON files(file_name);
                CREATE INDEX IF NOT EXISTS idx_name_size ON files(file_name, file_size);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_path ON files(file_path);
                """
            )
            self.conn.commit()

    def _rows(self, sql: str, args: tuple) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [dict(zip(_COLUMNS, row)) for row in rows]

    def find_by_name_and_size(self, name: str, size: int) -> list[dict]:
        return self._rows(
            "SELECT file_hash, file_name, file_size, file_path, category "
            "FROM files WHERE file_name=? AND file_size=?",
            (name, size),
        )

    def find_live(self, name: str, size: int) -> dict | None:
        """返回仍在磁盘上的记录，并清掉已经不存在的路径。"""
        found = None
        for row in self.find_by_name_and_size(name, size):
            if Path(row["path"]).exists():
                found = row
                break
            self.remove_by_path(row["path"])
        return found

    def add_file(self, file_hash: str, name: str, size: int, path: str, category: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO files (file_hash, file_name, file_size, file_path, category) "
                "VALUES (?, ?, ?, ?, ?)",
                (file_hash, name, size, path, category),
            )
            self.conn.commit()

    def update_hash(self, path: str, file_hash: str) -> None:
        if not file_hash:
            return
        with self._lock:
            self.conn.execute("UPDATE files SET file_hash=? WHERE file_path=?", (file_hash, path))
            self.conn.commit()

    def remove_by_path(self, path: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM files WHERE file_path=?", (path,))
            self.conn.commit()

    def stats(self) -> dict:
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            hashed = self.conn.execute(
                "SELECT COUNT(*) FROM files WHERE file_hash!=''"
            ).fetchone()[0]
            groups = self.conn.execute(
                "SELECT category, COUNT(*) FROM files GROUP BY category ORDER BY COUNT(*) DESC"
            ).fetchall()
        return {
            "total": total,
            "hashed": hashed,
            "by_cat": {(row[0] or "未分类"): row[1] for row in groups},
        }

    def close(self) -> None:
        with self._lock:
            self.conn.close()


def index_existing(base: Path, categories: dict, db: Database) -> int:
    from dlm.files import is_temp_file

    count = 0
    base = Path(base)
    if not base.exists():
        return 0
    for name in categories:
        folder = base / name
        if not folder.is_dir():
            continue
        try:
            children = folder.rglob("*")
        except OSError as exc:
            log.warning("无法扫描 %s (%s)", folder, exc)
            continue
        for path in children:
            if not path.is_file() or path.is_symlink() or is_temp_file(path):
                continue
            try:
                info = path.stat()
            except OSError:
                continue
            db.add_file("", path.name, info.st_size, str(path), name)
            count += 1
    log.info("初始扫描完成，已索引 %s 个文件", count)
    return count
