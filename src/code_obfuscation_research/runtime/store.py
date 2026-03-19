"""JSONL-based run artifact storage."""
import json
import logging
from pathlib import Path

from code_obfuscation_research.domain import RunRecord

logger = logging.getLogger(__name__)


class RunStore:
    """JSONL storage for run records. Clears previous file on init to avoid duplicates."""

    def __init__(self, output_dir: str | Path, experiment_name: str, perturbation_name: str):
        self.output_dir = Path(output_dir)
        self.experiment_name = experiment_name
        self.perturbation_name = perturbation_name
        self._path = self.output_dir / f"{experiment_name}_{perturbation_name}.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            logger.info("Clearing previous run file: %s", self._path)
            self._path.unlink()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: RunRecord) -> None:
        with open(self._path, "a") as f:
            f.write(json.dumps(record.to_dict()) + "\n")

    def load_all(self) -> list[RunRecord]:
        if not self._path.exists():
            return []
        records = []
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(RunRecord.from_dict(json.loads(line)))
        return records

    @staticmethod
    def load_from_path(path: str | Path) -> list[RunRecord]:
        path = Path(path)
        records = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(RunRecord.from_dict(json.loads(line)))
        return records
