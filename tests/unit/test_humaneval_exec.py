"""Tests for deterministic HumanEval execution evaluator."""
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
