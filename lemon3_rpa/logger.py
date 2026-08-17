from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def setup_logger(log_dir: str | Path) -> tuple[logging.Logger, Path]:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    logger = logging.getLogger("lemon3_rpa")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger, log_path
