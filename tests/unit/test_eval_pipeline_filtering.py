"""Tests for evaluator-specific record filtering in eval pipeline."""
from code_obfuscation_research.domain import RunRecord
from code_obfuscation_research.pipelines.eval_pipeline import (
    _filter_for_humaneval_exec,
    _filter_for_multipl_e_js_exec,
)


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


def test_filter_for_humaneval_exec_excludes_non_python_language():
    records = [
        _make_record(
            "HumanEval_js_0",
            {
                "language": "javascript",
                "prompt": "function f(x) {\n",
                "test": "}\nconsole.log('ok');",
                "entry_point": "f",
            },
        ),
    ]

    assert _filter_for_humaneval_exec(records) == []


def test_filter_for_multipl_e_js_exec_by_task_type():
    records = [
        _make_record("HumanEval_js_1", {"task_type": "multipl_e_humaneval_js"}),
        _make_record("HumanEval/1", {"task_type": "humaneval"}),
        _make_record("codeqa_0", {}),
    ]

    filtered = _filter_for_multipl_e_js_exec(records)

    assert [r.sample_id for r in filtered] == ["HumanEval_js_1"]


def test_filter_for_multipl_e_js_exec_by_language_and_required_metadata():
    records = [
        _make_record(
            "HumanEval_js_2",
            {
                "language": "javascript",
                "prompt": "function g(x) {\n",
                "test": "}\nconsole.log('ok');",
                "entry_point": "g",
            },
        ),
        _make_record(
            "py_row",
            {
                "language": "python",
                "prompt": "def g(x):\n",
                "test": "def check(c): pass",
                "entry_point": "g",
            },
        ),
    ]

    filtered = _filter_for_multipl_e_js_exec(records)

    assert [r.sample_id for r in filtered] == ["HumanEval_js_2"]
