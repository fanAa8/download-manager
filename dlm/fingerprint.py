"""重复文件指纹。小文件全量 MD5，大文件取头、中、尾，避免每次整文件哈希。"""

from __future__ import annotations

import hashlib
from pathlib import Path

HASH_THRESHOLD = 524288000  # 500MB
_SAMPLE = 1024 * 1024


def smart_fingerprint(
    path: Path,
    threshold: int = HASH_THRESHOLD,
    sample: int = _SAMPLE,
    chunk: int = 1024 * 1024,
) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    digest = hashlib.md5()
    try:
        with open(path, "rb") as handle:
            if size < threshold:
                while True:
                    block = handle.read(chunk)
                    if not block:
                        break
                    digest.update(block)
                return "md5:" + digest.hexdigest()
            digest.update(handle.read(sample))
            handle.seek(max(0, size // 2 - sample // 2))
            digest.update(handle.read(sample))
            handle.seek(max(0, size - sample))
            digest.update(handle.read(sample))
    except OSError:
        return ""
    return "sample-md5:" + digest.hexdigest()


def usable_fingerprint(value: str) -> bool:
    return bool(value) and (value.startswith("md5:") or value.startswith("sample-md5:"))
