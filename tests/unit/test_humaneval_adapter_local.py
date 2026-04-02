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
