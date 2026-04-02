"""HuggingFace adapter for openai/openai_humaneval."""
import json
import logging
from pathlib import Path

from datasets import load_dataset

from code_obfuscation_research.domain import CodeArtifact, HumanEvalSample

logger = logging.getLogger(__name__)


def _artifact_id(task_id: str) -> str:
    return f"{task_id.replace('/', '_')}_prompt"


class HumanEvalDatasetAdapter:
    """Loads HumanEval rows and normalizes them into HumanEvalSample objects."""

    def __init__(
        self,
        hf_dataset_name: str = "openai/openai_humaneval",
        split: str = "test",
        language: str = "python",
        local_path: str | None = None,
    ):
        self.hf_dataset_name = hf_dataset_name
        self.split = split
        self.language = language
        self.local_path = local_path

    def _row_to_sample(self, row: dict | object) -> HumanEvalSample | None:
        raw = dict(row) if not isinstance(row, dict) else row
        task_id = raw.get("task_id", "")
        prompt = raw.get("prompt", "")
        test = raw.get("test", "")
        entry_point = raw.get("entry_point", "")
        if not isinstance(task_id, str) or not isinstance(prompt, str):
            return None
        if not isinstance(test, str) or not isinstance(entry_point, str):
            return None
        if not prompt or not test or not entry_point or not task_id:
            return None
        canonical = raw.get("canonical_solution", "")
        if not isinstance(canonical, str):
            canonical = ""
        return HumanEvalSample(
            sample_id=task_id,
            code=CodeArtifact(
                artifact_id=_artifact_id(task_id),
                text=prompt,
                language=self.language,
            ),
            entry_point=entry_point,
            test=test,
            canonical_solution=canonical,
        )

    def _load_from_local(self, limit: int | None) -> list[HumanEvalSample]:
        path = Path(self.local_path)  # type: ignore[arg-type]
        samples: list[HumanEvalSample] = []
        with open(path) as f:
            for line in f:
                if limit is not None and len(samples) >= limit:
                    break
                row = json.loads(line)
                sample = self._row_to_sample(row)
                if sample:
                    samples.append(sample)
        logger.info("Loaded %d samples from local %s (limit=%s)", len(samples), path, limit)
        return samples

    def _load_from_hf(self, split: str, limit: int | None) -> list[HumanEvalSample]:
        ds = load_dataset(self.hf_dataset_name, split=split, streaming=True)
        samples: list[HumanEvalSample] = []
        for row in ds:
            if limit is not None and len(samples) >= limit:
                break
            sample = self._row_to_sample(row)
            if sample:
                samples.append(sample)
        logger.info("Loaded %d samples from %s (split=%s, limit=%s)", len(samples), self.hf_dataset_name, split, limit)
        return samples

    def load_split(self, split: str | None = None, limit: int | None = None) -> list[HumanEvalSample]:
        if self.local_path:
            return self._load_from_local(limit)
        effective = self.split if split is None else split
        return self._load_from_hf(effective, limit)
