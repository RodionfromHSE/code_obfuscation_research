"""Tests for evaluator-specific record filtering in eval pipeline."""
from code_obfuscation_research.domain import RunRecord
from code_obfuscation_research.pipelines.eval_pipeline import _filter_for_humaneval_exec


def _make_record(sample_id: str, metadata: dict) -> RunRecord:
    return RunRecord(
        sample_id=sample_id,
        perturbation_name="noop",
        request_messages=[{"role": "user", "content": "x"}],
        response_text="y",
        reference_text="z",
        metadata=metadata,
    )


def test_filter_for_humaneval_exec_by_task_type():
    records = [
        _make_record("codeqa_0", {"task_type": "codeqa"}),
        _make_record("HumanEval/1", {"task_type": "humaneval", "entry_point": "f"}),
        _make_record("codeqa_1", {}),
    ]

    filtered = _filter_for_humaneval_exec(records)

    assert [r.sample_id for r in filtered] == ["HumanEval/1"]


def test_filter_for_humaneval_exec_by_required_metadata():
    records = [
        _make_record(
            "HumanEval/2",
            {
                "prompt": "def f(x):\n",
                "test": "def check(candidate):\n    pass",
                "entry_point": "f",
            },
        ),
        _make_record(
            "bad_row",
            {
                "prompt": "def g(x):\n",
                "test": "def check(candidate):\n    pass",
                "entry_point": 123,
            },
        ),
    ]

    filtered = _filter_for_humaneval_exec(records)

    assert [r.sample_id for r in filtered] == ["HumanEval/2"]
