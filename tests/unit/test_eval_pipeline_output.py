"""Tests for HumanEval evaluation summary output."""
from code_obfuscation_research.evaluation.deepeval_runner import CorrectnessResult
from code_obfuscation_research.pipelines.eval_pipeline import _print_failed_ids


def test_print_failed_ids_shows_sample_ids(capsys):
    results = [
        CorrectnessResult(
            sample_id="HumanEval/1",
            perturbation_name="noop",
            is_correct=False,
            score=0.0,
            reason="AssertionError",
        ),
        CorrectnessResult(
            sample_id="HumanEval/2",
            perturbation_name="noop",
            is_correct=True,
            score=1.0,
            reason="passed",
        ),
    ]

    _print_failed_ids(results)
    out = capsys.readouterr().out
    assert "Failed HumanEval task IDs:" in out
    assert "HumanEval/1" in out
    assert "AssertionError" in out


def test_print_failed_ids_all_pass(capsys):
    results = [
        CorrectnessResult(
            sample_id="HumanEval/2",
            perturbation_name="noop",
            is_correct=True,
            score=1.0,
            reason="passed",
        )
    ]

    _print_failed_ids(results)
    out = capsys.readouterr().out
    assert "All HumanEval task IDs passed." in out
