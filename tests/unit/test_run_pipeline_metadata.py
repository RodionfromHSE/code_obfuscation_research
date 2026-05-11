"""Tests for run pipeline record metadata handling."""
from code_obfuscation_research.domain import CodeArtifact, HumanEvalSample, ModelResponse
from code_obfuscation_research.perturbations.python_rename_symbols import RenameSymbolsPerturbation
from code_obfuscation_research.pipelines.run_pipeline import _build_request, _to_record
from code_obfuscation_research.tasks.humaneval import HumanEvalTask


def test_to_record_includes_request_metadata():
    sample = HumanEvalSample(
        sample_id="HumanEval/1",
        code=CodeArtifact(artifact_id="h1", text="def f(x):\n"),
        metadata={"source": "test"},
        entry_point="f",
        test="def check(candidate):\n    assert candidate(1) == 2",
        canonical_solution="    return x + 1",
    )
    task = HumanEvalTask()
    request = task.build_request(sample, sample.code)
    response = ModelResponse(
        sample_id=sample.sample_id,
        perturbation_name="noop",
        text="    return x + 1",
    )

    record = _to_record(
        sample=sample,
        task=task,
        request=request,
        response=response,
        perturbation_name="noop",
        perturbation_stats={},
    )

    assert record.metadata["source"] == "test"
    assert record.metadata["entry_point"] == "f"
    assert "check(candidate)" in str(record.metadata["test"])


def test_build_request_remaps_humaneval_entrypoint_when_function_renamed():
    sample = HumanEvalSample(
        sample_id="HumanEval/42",
        code=CodeArtifact(
            artifact_id="h42",
            text="def target_fn(x):\n    \"\"\"return x + 1\"\"\"\n",
        ),
        entry_point="target_fn",
        test="def check(candidate):\n    assert candidate(1) == 2",
        canonical_solution="    return x + 1",
    )
    task = HumanEvalTask()
    perturbation = RenameSymbolsPerturbation(
        rename_functions=True,
        rename_classes=False,
        rename_parameters=False,
    )

    request, stats = _build_request(
        sample=sample,
        task=task,
        perturbation=perturbation,
        perturbation_name="rename_symbols",
    )

    assert isinstance(stats.get("renamed_function_map"), dict)
    assert request.metadata["original_entry_point"] == "target_fn"
    assert request.metadata["entry_point"] == "func_0"
