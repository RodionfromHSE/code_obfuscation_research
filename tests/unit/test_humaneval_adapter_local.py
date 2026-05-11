"""Tests for HumanEval adapter local JSONL loading."""
import json

from code_obfuscation_research.datasets.human_eval import HumanEvalDatasetAdapter


def test_load_from_local_jsonl(tmp_path):
    path = tmp_path / "humaneval.jsonl"
    rows = [
        {
            "task_id": "HumanEval/1",
            "prompt": "def f(x):\n",
            "test": "def check(candidate):\n    assert candidate(1) == 2\n",
            "entry_point": "f",
            "canonical_solution": "    return x + 1",
        },
        {
            "task_id": "HumanEval/2",
            "prompt": "",
            "test": "def check(candidate):\n    assert candidate(1) == 1\n",
            "entry_point": "g",
        },
    ]
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    adapter = HumanEvalDatasetAdapter(local_path=str(path))
    samples = adapter.load_split(limit=10)

    assert len(samples) == 1
    assert samples[0].sample_id == "HumanEval/1"
    assert samples[0].entry_point == "f"
    assert "check(candidate)" in samples[0].test


def test_loads_multipl_e_style_local_jsonl(tmp_path):
    path = tmp_path / "multipl_e_js.jsonl"
    row = {
        "name": "HumanEval_1_f",
        "language": "js",
        "prompt": "function f(x) {\n",
        "tests": (
            "const assert = require('assert');\n"
            "function check(candidate) { assert.strictEqual(candidate(1), 2); }\n"
        ),
        "entry_point": "f",
        "canonical_solution": "return x + 1;\n}",
    }
    with open(path, "w") as f:
        f.write(json.dumps(row) + "\n")

    adapter = HumanEvalDatasetAdapter(local_path=str(path), language="js")
    samples = adapter.load_split(limit=1)

    assert len(samples) == 1
    assert samples[0].sample_id == "HumanEval_1_f"
    assert samples[0].code.language == "js"
    assert "assert.strictEqual" in samples[0].test
