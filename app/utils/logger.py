"""Logging configuration for PhoneLink Ubuntu."""

import logging
import sys
from pathlib import Path

LOG_DIR = Path.home() / ".local" / "share" / "phonelink-ubuntu"
LOG_FILE = LOG_DIR / "phonelink.log"
_initialized = False


def setup_logging(level: int = logging.DEBUG) -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    fmt = "%(asctime)s [%(levelname)-8s] %(name)-30s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(console)

    try:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        root.addHandler(fh)
    except OSError as exc:
        root.warning("Cannot write log file %s: %s", LOG_FILE, exc)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
