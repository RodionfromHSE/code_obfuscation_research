"""Tests for run pipeline record metadata handling."""
from code_obfuscation_research.domain import CodeArtifact, HumanEvalSample, ModelResponse
from code_obfuscation_research.pipelines.run_pipeline import _to_record
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
