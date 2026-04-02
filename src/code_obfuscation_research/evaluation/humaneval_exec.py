"""Deterministic HumanEval execution-based evaluator (pass@1)."""
import re
import subprocess
import sys
from collections.abc import Mapping

from code_obfuscation_research.domain import EvalCase
from code_obfuscation_research.evaluation.deepeval_runner import CorrectnessResult

_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*\n(?P<code>[\s\S]*?)```", re.IGNORECASE)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _extract_code(text: str) -> str:
    match = _CODE_BLOCK_RE.search(text)
    if not match:
        return text
    return match.group("code")


def _build_candidate_program(prompt: str, completion: str, entry_point: str) -> str:
    completion_code = _extract_code(completion).strip("\n")
    if f"def {entry_point}" in completion_code:
        return completion_code
    return f"{prompt.rstrip()}\n{completion_code}\n"


def _build_exec_script(candidate_program: str, test_code: str, entry_point: str) -> str:
    return (
        f"{candidate_program.rstrip()}\n\n"
        f"{test_code.rstrip()}\n\n"
        f"check(globals()[{entry_point!r}])\n"
    )


def _truncate(text: str, limit: int = 300) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "..."


def run_humaneval_exec(case: EvalCase, timeout_seconds: float = 3.0) -> CorrectnessResult:
    """Execute one HumanEval case and return binary correctness."""
    metadata: Mapping[str, object] = case.metadata
    prompt = metadata.get("prompt")
    entry_point = metadata.get("entry_point")
    test_code = metadata.get("test")

    if not isinstance(prompt, str) or not prompt.strip():
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=False,
            score=None,
            reason="error: missing metadata.prompt",
        )
    if not isinstance(entry_point, str) or not entry_point.strip():
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=False,
            score=None,
            reason="error: missing metadata.entry_point",
        )
    if _IDENT_RE.fullmatch(entry_point.strip()) is None:
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=False,
            score=None,
            reason="error: invalid metadata.entry_point",
        )
    if not isinstance(test_code, str) or not test_code.strip():
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=False,
            score=None,
            reason="error: missing metadata.test",
        )

    candidate_program = _build_candidate_program(prompt, case.actual_output, entry_point)
    script = _build_exec_script(candidate_program, test_code, entry_point)

    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=False,
            score=0.0,
            reason=f"timeout ({timeout_seconds}s)",
        )
    except Exception as e:
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=False,
            score=None,
            reason=f"error: {e}",
        )

    if completed.returncode == 0:
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=True,
            score=1.0,
            reason="passed",
        )

    stderr = completed.stderr.strip() or completed.stdout.strip() or "execution failed"
    return CorrectnessResult(
        sample_id=case.sample_id,
        perturbation_name=case.perturbation_name,
        is_correct=False,
        score=0.0,
        reason=_truncate(stderr),
    )
