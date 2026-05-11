"""HuggingFace adapter for nuprl/MultiPL-E (HumanEval translations to non-Python languages)."""
import json
import logging
import re
from pathlib import Path

from datasets import load_dataset

from code_obfuscation_research.domain import CodeArtifact, HumanEvalSample

logger = logging.getLogger(__name__)

# matches the last top-level `function NAME(` in a MultiPL-E JS/TS prompt.
_JS_FUNCTION_DECL_RE = re.compile(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")


def _artifact_id(name: str) -> str:
    return f"{name.replace('/', '_')}_prompt"


def _extract_js_entry_point(prompt: str) -> str | None:
    """Return the last `function NAME(` declared in a MultiPL-E JS prompt, if any.

    MultiPL-E prompts end with the signature of the function to implement; we use
    the *last* match because some prompts include helper declarations earlier.
    """
    matches = _JS_FUNCTION_DECL_RE.findall(prompt)
    if not matches:
        return None
    return matches[-1]


class MultiPLEDatasetAdapter:
    """Loads MultiPL-E rows and normalizes them into HumanEvalSample objects."""

    def __init__(
        self,
        hf_dataset_name: str = "nuprl/MultiPL-E",
        hf_config: str = "humaneval-js",
        split: str = "test",
        language: str = "javascript",
        local_path: str | None = None,
    ):
        self.hf_dataset_name = hf_dataset_name
        self.hf_config = hf_config
        self.split = split
        self.language = language
        self.local_path = local_path

    def _row_to_sample(self, row: dict | object) -> HumanEvalSample | None:
        raw = dict(row) if not isinstance(row, dict) else row
        name = raw.get("name", "")
        prompt = raw.get("prompt", "")
        tests = raw.get("tests", "")
        if not isinstance(name, str) or not isinstance(prompt, str) or not isinstance(tests, str):
            return None
        if not name or not prompt or not tests:
            return None
        entry_point = _extract_js_entry_point(prompt)
        if not entry_point:
            logger.debug("Skipping %s: could not extract entry point from prompt", name)
            return None
        return HumanEvalSample(
            sample_id=name,
            code=CodeArtifact(
                artifact_id=_artifact_id(name),
                text=prompt,
                language=self.language,
            ),
            entry_point=entry_point,
            test=tests,
            canonical_solution="",
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
        ds = load_dataset(self.hf_dataset_name, self.hf_config, split=split, streaming=True)
        samples: list[HumanEvalSample] = []
        for row in ds:
            if limit is not None and len(samples) >= limit:
                break
            sample = self._row_to_sample(row)
            if sample:
                samples.append(sample)
        logger.info(
            "Loaded %d samples from %s/%s (split=%s, limit=%s)",
            len(samples), self.hf_dataset_name, self.hf_config, split, limit,
        )
        return samples

    def load_split(self, split: str | None = None, limit: int | None = None) -> list[HumanEvalSample]:
        if self.local_path:
            return self._load_from_local(limit)
        effective = self.split if split is None else split
        return self._load_from_hf(effective, limit)
