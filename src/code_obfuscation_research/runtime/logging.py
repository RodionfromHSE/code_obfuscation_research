"""Logging configuration: file gets everything, console stays quiet."""
import logging
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
NOISY_LOGGERS = ("httpx", "httpcore", "openai", "httpx._client")


def configure_logging(log_file: str | Path) -> None:
    """Set up root logger with file (DEBUG+) and console (WARNING+) handlers."""
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    fmt = logging.Formatter(LOG_FORMAT)

    fh = logging.FileHandler(log_path)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
