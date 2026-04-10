"""Logging setup for swe_task: file-based detail + clean stdout."""
import io
import logging
import os
import sys
from pathlib import Path

_NOISY_LOGGERS = [
    "LiteLLM", "LiteLLM Router", "LiteLLM Proxy",
    "litellm", "litellm_model",
    "httpx", "httpcore", "openai", "urllib3",
    "datasets", "huggingface_hub", "filelock",
    "agent", "swebench",
    "minisweagent",
]


def configure_logging(log_dir: Path, experiment_name: str) -> Path:
    """Set up dual logging: verbose file + terse stdout."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{experiment_name}.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    for h in root.handlers[:]:
        root.removeHandler(h)

    file_handler = logging.FileHandler(log_file, mode="w")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    console_handler.addFilter(lambda record: record.name.startswith("swe_task"))
    root.addHandler(console_handler)

    _silence_third_party()
    _redirect_stderr_to(log_file)

    logging.getLogger("swe_task").info("Logging to %s", log_file)
    return log_file


def _silence_third_party() -> None:
    """Set noisy loggers to ERROR and strip their pre-attached StreamHandlers."""
    for name in _NOISY_LOGGERS:
        lg = logging.getLogger(name)
        lg.setLevel(logging.ERROR)
        lg.propagate = False
        for h in lg.handlers[:]:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                lg.removeHandler(h)


def _redirect_stderr_to(log_file: Path) -> None:
    """Redirect fd 2 to the log file so raw print(..., file=sys.stderr) goes there."""
    try:
        log_fd = os.open(str(log_file), os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        os.dup2(log_fd, 2)
        os.close(log_fd)
        sys.stderr = io.TextIOWrapper(os.fdopen(2, "wb", closefd=False), write_through=True)
    except OSError:
        pass
