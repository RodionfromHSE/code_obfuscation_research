"""DeepEval binary correctness runner (GEval with strict_mode)."""
import logging
from dataclasses import dataclass

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

from code_obfuscation_research.domain import EvalCase

logger = logging.getLogger(__name__)


@dataclass
class CorrectnessResult:
    sample_id: str
    perturbation_name: str
    is_correct: bool
    score: float | None
    reason: str


def build_correctness_metric(
    evaluation_steps: list[str],
    threshold: float = 0.5,
    model: str = "gpt-5.4-mini-2026-03-17",
) -> GEval:
    """Binary correctness: score is 0 or 1."""
    return GEval(
        name="Correctness",
        criteria="Is the actual output factually correct given the expected output? Answer yes (1) or no (0).",
        evaluation_steps=evaluation_steps,
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
        ],
        threshold=threshold,
        model=model,
        strict_mode=True,
    )


def run_correctness(metric: GEval, case: EvalCase) -> CorrectnessResult:
    test_case = LLMTestCase(
        input=case.input_text,
        actual_output=case.actual_output,
        expected_output=case.expected_output,
    )
    try:
        metric.measure(test_case)
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=metric.score == 1.0,
            score=metric.score,
            reason=metric.reason or "",
        )
    except Exception as e:
        logger.warning("Correctness eval failed for %s: %s", case.sample_id, e)
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=False,
            score=None,
            reason=f"error: {e}",
        )


async def arun_correctness(metric: GEval, case: EvalCase) -> CorrectnessResult:
    test_case = LLMTestCase(
        input=case.input_text,
        actual_output=case.actual_output,
        expected_output=case.expected_output,
    )
    try:
        await metric.a_measure(test_case)
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=metric.score == 1.0,
            score=metric.score,
            reason=metric.reason or "",
        )
    except Exception as e:
        logger.warning("Correctness eval async failed for %s: %s", case.sample_id, e)
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=False,
            score=None,
            reason=f"error: {e}",
        )
