"""tqdm-backed monitor that polls swebench's log dir for completed reports."""
import logging
import sys
import threading
from pathlib import Path

from tqdm import tqdm

logger = logging.getLogger(__name__)


class EvalProgressMonitor:
    """Polls swebench log directory for report.json files and drives a tqdm bar.

    swebench's run_evaluation doesn't expose progress callbacks, so we watch
    the filesystem: one `report.json` appears per completed instance.
    """

    def __init__(
        self,
        logs_dir: Path,
        total: int,
        interval: float = 5.0,
        desc: str = "Docker eval",
    ):
        self._logs_dir = logs_dir
        self._total = max(total, 0)
        self._interval = interval
        self._desc = desc
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pbar: tqdm | None = None

    def start(self) -> None:
        if self._total == 0:
            logger.info("Docker eval: nothing to evaluate (total=0)")
            return
        self._pbar = tqdm(
            total=self._total,
            desc=self._desc,
            unit="inst",
            file=sys.stdout,
            dynamic_ncols=True,
            smoothing=0.3,
        )
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._pbar is not None:
            self._pbar.n = min(self._pbar.total, self._current_count())
            self._pbar.refresh()
            self._pbar.close()

    def _current_count(self) -> int:
        if not self._logs_dir.exists():
            return 0
        return sum(1 for _ in self._logs_dir.rglob("report.json"))

    def _poll(self) -> None:
        last = 0
        while not self._stop.wait(self._interval):
            if self._pbar is None:
                return
            count = self._current_count()
            delta = count - last
            if delta > 0:
                self._pbar.update(delta)
                last = count
