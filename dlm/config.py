"""配置读写。损坏的文件会留备份，不会让程序起不来。"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
from pathlib import Path

from dlm.paths import config_path, default_config_path

log = logging.getLogger("DLM")

DEFAULTS = {
    "watch_folders": [],
    "target_base": "",
    "download_complete_wait": 5,
    "batch_window": 15,
    "batch_max_wait": 300,
    "settle_window": 3,
    "hash_chunk_size": 8388608,
    "min_file_size_for_hash": 1024,
    "default_category": "其他",
    "categories": {},
    "time_saving": False,
    "hard_delete_duplicates": False,
    "duplicate_action": "quarantine",
    "poll_interval": 2,
    "file_max_wait": 1800,
    "offline_hold_seconds": 600,
}

INT_RANGES = {
    "download_complete_wait": (2, 120),
    "batch_window": (2, 180),
    "batch_max_wait": (30, 7200),
    "settle_window": (1, 60),
    "hash_chunk_size": (64 * 1024, 64 * 1024 * 1024),
    "min_file_size_for_hash": (0, 10**12),
    "poll_interval": (1, 30),
    "file_max_wait": (30, 86400),
    "offline_hold_seconds": (0, 7200),
}

DUPLICATE_ACTIONS = {"quarantine", "recycle", "delete", "ask"}


def normalize(cfg: dict | None) -> dict:
    raw = cfg if isinstance(cfg, dict) else {}
    out = dict(raw)
    for key, value in DEFAULTS.items():
        if key not in out and key != "duplicate_action":
            out[key] = copy.deepcopy(value)
    requested = str(raw.get("duplicate_action") or "").strip().lower()
    if requested in DUPLICATE_ACTIONS:
        action = requested
    elif raw.get("hard_delete_duplicates"):
        action = "delete"
    else:
        action = "quarantine"
    folders = out.get("watch_folders")
    if isinstance(out.get("watch_path"), str) and out["watch_path"].strip():
        folders = list(folders or []) + [out["watch_path"]]
    if not isinstance(folders, list):
        folders = []
    out["watch_folders"] = [str(item).strip() for item in folders if str(item).strip()]
    out.pop("watch_path", None)
    out["target_base"] = str(out.get("target_base") or "").strip()
    for key, (low, high) in INT_RANGES.items():
        try:
            number = int(out.get(key, DEFAULTS[key]))
        except (TypeError, ValueError):
            number = DEFAULTS[key]
        out[key] = max(low, min(high, number))
    out["duplicate_action"] = action
    out["hard_delete_duplicates"] = action == "delete"
    if not isinstance(out.get("categories"), dict):
        out["categories"] = {}
    if not str(out.get("default_category") or "").strip():
        out["default_category"] = "其他"
    else:
        out["default_category"] = str(out["default_category"])
    out["time_saving"] = bool(out.get("time_saving", False))
    return out


def read_template(default_path: Path | None = None) -> dict:
    path = default_path if default_path is not None else default_config_path()
    if path is None or not path.is_file():
        return normalize({"categories": {"其他": {"extensions": [], "role": "other"}}})
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("默认配置无法读取 %s (%s)", path, exc)
        return normalize({"categories": {"其他": {"extensions": [], "role": "other"}}})
    return normalize(data if isinstance(data, dict) else {})


def _backup_bad(path: Path) -> Path:
    backup = path.with_name(path.name + ".bad")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.{counter}.bad")
        counter += 1
    shutil.copy2(path, backup)
    return backup


def load_config(path: Path | None = None, default_path: Path | None = None) -> dict:
    target = Path(path) if path is not None else config_path()
    template = lambda: read_template(default_path)  # noqa: E731
    if not target.exists():
        cfg = template()
        save_config(cfg, target)
        log.info("已创建配置: %s", target)
        return cfg
    try:
        text = target.read_text(encoding="utf-8-sig")
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        backup = _backup_bad(target)
        log.error("配置损坏，已备份到 %s (%s)，改用默认配置", backup, exc)
        cfg = template()
        save_config(cfg, target)
        return cfg
    except OSError as exc:
        log.error("配置无法读取 %s (%s)", target, exc)
        return template()
    if not isinstance(data, dict):
        backup = _backup_bad(target)
        log.error("配置格式不正确，已备份到 %s", backup)
        cfg = template()
        save_config(cfg, target)
        return cfg
    cfg = normalize(data)
    if not cfg["categories"]:
        cfg["categories"] = template()["categories"]
    return cfg


def save_config(cfg: dict, path: Path | None = None) -> dict:
    target = Path(path) if path is not None else config_path()
    normalized = normalize(cfg)
    target.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(blob, encoding="utf-8")
    os.replace(temporary, target)
    return normalized
