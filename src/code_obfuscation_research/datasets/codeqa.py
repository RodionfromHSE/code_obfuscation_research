"""HuggingFace adapter for vm2825/CodeQA-dataset."""
import json
import logging
from pathlib import Path

from datasets import load_dataset

from code_obfuscation_research.domain import CodeArtifact, CodeQASample

logger = logging.getLogger(__name__)


class CodeQADatasetAdapter:
    """Loads CodeQA rows and normalizes them into CodeQASample objects."""

    def __init__(
        self,
        hf_dataset_name: str = "vm2825/CodeQA-dataset",
        split: str = "train",
        language: str = "python",
        local_path: str | None = None,
    ):
        self.hf_dataset_name = hf_dataset_name
        self.split = split
        self.language = language
        self.local_path = local_path

    def _row_to_sample(self, row: dict, row_idx: int) -> CodeQASample | None:
        code_text = row.get("input_code", "")
        question = row.get("Instruction", "")
        answer = row.get("output_code", "")
        if not code_text or not question:
            return None
        return CodeQASample(
            sample_id=f"codeqa_{row_idx}",
            code=CodeArtifact(artifact_id=f"codeqa_{row_idx}_code", text=code_text, language=self.language),
            question=question,
            answer=answer,
        )

    def _load_from_local(self, limit: int | None) -> list[CodeQASample]:
        path = Path(self.local_path)  # type: ignore[arg-type]
        samples: list[CodeQASample] = []
        with open(path) as f:
            for row_idx, line in enumerate(f):
                if limit is not None and len(samples) >= limit:
                    break
                row = json.loads(line)
                sample = self._row_to_sample(row, row_idx)
                if sample:
                    samples.append(sample)
        logger.info("Loaded %d samples from local %s (limit=%s)", len(samples), path, limit)
        return samples

    def _load_from_hf(self, split: str, limit: int | None) -> list[CodeQASample]:
        ds = load_dataset(self.hf_dataset_name, split=split, streaming=True)
        samples: list[CodeQASample] = []
        row_idx = 0
        for row in ds:
            if limit is not None and len(samples) >= limit:
                break
            sample = self._row_to_sample(row, row_idx)
            if sample:
                samples.append(sample)
            row_idx += 1
        logger.info("Loaded %d samples from %s (split=%s, limit=%s)", len(samples), self.hf_dataset_name, split, limit)
        return samples

    def load_split(self, split: str = "train", limit: int | None = None) -> list[CodeQASample]:
        if self.local_path:
            return self._load_from_local(limit)
        split = split or self.split
        return self._load_from_hf(split, limit)
