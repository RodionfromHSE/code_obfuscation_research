"""Integration test: load 3 CodeQA samples from HuggingFace."""
import pytest

from code_obfuscation_research.datasets.codeqa import CodeQADatasetAdapter
from code_obfuscation_research.domain import CodeQASample


@pytest.mark.timeout(30)
def test_load_3_samples():
    adapter = CodeQADatasetAdapter()
    samples = adapter.load_split(limit=3)
    assert len(samples) == 3
    for s in samples:
        assert isinstance(s, CodeQASample)
        assert s.code.text
        assert s.question
        assert s.code.language == "python"
