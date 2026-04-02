"""Integration test: load HumanEval samples from HuggingFace."""
import pytest

from code_obfuscation_research.datasets.human_eval import HumanEvalDatasetAdapter
from code_obfuscation_research.domain import HumanEvalSample


@pytest.mark.timeout(30)
def test_load_3_samples():
    adapter = HumanEvalDatasetAdapter()
    samples = adapter.load_split(limit=3)
    assert len(samples) == 3
    for s in samples:
        assert isinstance(s, HumanEvalSample)
        assert s.code.text
        assert s.test
        assert s.entry_point
        assert s.sample_id.startswith("HumanEval/")
        assert s.code.language == "python"
