"""Smoke test: perturb 3 real CodeQA samples with rename_symbols."""
import ast

import pytest

from code_obfuscation_research.datasets.codeqa import CodeQADatasetAdapter
from code_obfuscation_research.domain import PerturbationInput
from code_obfuscation_research.perturbations.python_rename_symbols import RenameSymbolsPerturbation


@pytest.mark.timeout(30)
def test_perturb_3_real_samples():
    adapter = CodeQADatasetAdapter()
    samples = adapter.load_split(limit=3)
    perturbation = RenameSymbolsPerturbation()

    for sample in samples:
        inp = PerturbationInput(code=sample.code, sample_id=sample.sample_id)
        result = perturbation.apply(inp)
        if result.applied:
            ast.parse(result.perturbed_code.text)
        assert result.error is None or "parse error" in result.error
