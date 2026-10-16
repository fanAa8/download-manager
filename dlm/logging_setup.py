"""滚动日志。窗口程序没有控制台时仍然把记录写到 exe 旁边。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from dlm.paths import log_path

LOG = logging.getLogger("DLM")


def setup_logging(debug: bool = False) -> logging.Logger:
    LOG.setLevel(logging.DEBUG if debug else logging.INFO)
    LOG.handlers.clear()
    LOG.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        LOG.addHandler(file_handler)
    except OSError as exc:
        LOG.addHandler(logging.NullHandler())
        stream = sys.stderr or sys.stdout
        if stream is not None:
            print(f"无法写入日志文件: {exc}", file=stream)
    stream = sys.stdout if sys.stdout is not None else sys.stderr
    if stream is not None:
        console = logging.StreamHandler(stream)
        console.setFormatter(formatter)
        LOG.addHandler(console)
    return LOG
