"""Tests for deterministic HumanEval execution evaluator."""
import shutil

import pytest

from code_obfuscation_research.domain import EvalCase
from code_obfuscation_research.evaluation.humaneval_exec import run_humaneval_exec


def _make_case(actual_output: str) -> EvalCase:
    return EvalCase(
        sample_id="HumanEval/14",
        input_text="prompt",
        actual_output=actual_output,
        expected_output="",
        perturbation_name="noop",
        metadata={
            "prompt": (
                "from typing import List\n\n"
                "def all_prefixes(string: str) -> List[str]:\n"
                '    """Return list of all prefixes from shortest to longest."""\n'
            ),
            "entry_point": "all_prefixes",
            "test": (
                "def check(candidate):\n"
                "    assert candidate('') == []\n"
                "    assert candidate('asdfgh') == ['a', 'as', 'asd', 'asdf', 'asdfg', 'asdfgh']\n"
            ),
        },
    )


def test_pass_case():
    case = _make_case("    return [string[:i + 1] for i in range(len(string))]")
    result = run_humaneval_exec(case, timeout_seconds=2.0)
    assert result.is_correct is True
    assert result.score == 1.0


def test_fail_case():
    case = _make_case("    return ['x']")
    result = run_humaneval_exec(case, timeout_seconds=2.0)
    assert result.is_correct is False
    assert result.score == 0.0


def test_full_function_completion_keeps_prompt_imports():
    case = _make_case(
        "def all_prefixes(string: str) -> List[str]:\n"
        "    return [string[:i + 1] for i in range(len(string))]"
    )
    result = run_humaneval_exec(case, timeout_seconds=2.0)
    assert result.is_correct is True
    assert result.score == 1.0


def test_unindented_body_completion_is_indented_into_prompt():
    case = EvalCase(
        sample_id="HumanEval/2",
        input_text="prompt",
        actual_output="return number - int(number)",
        expected_output="",
        perturbation_name="noop",
        metadata={
            "prompt": "\n\ndef truncate_number(number: float) -> float:\n",
            "entry_point": "truncate_number",
            "test": (
                "def check(candidate):\n"
                "    assert candidate(3.5) == 0.5\n"
                "    assert abs(candidate(1.33) - 0.33) < 1e-6\n"
            ),
        },
    )
    result = run_humaneval_exec(case, timeout_seconds=2.0)
    assert result.is_correct is True
    assert result.score == 1.0


def test_missing_metadata_is_error():
    case = EvalCase(
        sample_id="HumanEval/14",
        input_text="prompt",
        actual_output="    return []",
        expected_output="",
        perturbation_name="noop",
        metadata={},
    )
    result = run_humaneval_exec(case, timeout_seconds=1.0)
    assert result.is_correct is False
    assert result.score is None
    assert "missing metadata.prompt" in result.reason


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_javascript_pass_case():
    case = EvalCase(
        sample_id="HumanEval_1_f",
        input_text="prompt",
        actual_output="return x + 1;\n}",
        expected_output="",
        perturbation_name="noop",
        metadata={
            "prompt": "function f(x) {\n",
            "entry_point": "f",
            "test": (
                "const assert = require('assert');\n"
                "function check(candidate) {\n"
                "  assert.strictEqual(candidate(1), 2);\n"
                "}\n"
            ),
            "language": "js",
        },
    )
    result = run_humaneval_exec(case, timeout_seconds=2.0)
    assert result.is_correct is True
    assert result.score == 1.0
