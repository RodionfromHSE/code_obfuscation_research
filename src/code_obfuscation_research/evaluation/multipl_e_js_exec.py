"""Deterministic MultiPL-E JavaScript execution-based evaluator (pass@1).

MultiPL-E `tests` typically open with `}` to close the prompt's incomplete
`function NAME(args) {`. When the model returns a *complete* function
declaration we strip the leading `}` so we don't end up with a stray brace.
"""
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

from code_obfuscation_research.domain import EvalCase
from code_obfuscation_research.evaluation.deepeval_runner import CorrectnessResult

_CODE_BLOCK_RE = re.compile(r"```(?:javascript|js)?\s*\n(?P<code>[\s\S]*?)```", re.IGNORECASE)
_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_LEADING_CLOSE_BRACE_RE = re.compile(r"^\s*\}\s*")


def _extract_code(text: str) -> str:
    match = _CODE_BLOCK_RE.search(text)
    if not match:
        return text
    return match.group("code")


def _defines_function(code: str, function_name: str) -> bool:
    """True when `code` already contains a complete declaration of `function_name`.

    Accepts the four common forms emitted by chat models:
      function NAME( ... )
      const NAME = ( ... ) => ...
      let   NAME = ( ... ) => ...
      var   NAME = ( ... ) => ...
    """
    escaped = re.escape(function_name)
    patterns = [
        rf"\bfunction\s+{escaped}\s*\(",
        rf"\b(?:const|let|var)\s+{escaped}\s*=",
    ]
    return any(re.search(p, code) for p in patterns)


def _build_candidate_program(
    prompt: str,
    completion: str,
    entry_point: str,
    original_entry_point: str | None,
    tests: str,
) -> tuple[str, str]:
    """Return (program, tests) ready for concatenation.

    Two cases:
      1. Completion already defines the function -> use it as the full program,
         and strip the leading `}` from tests (it was meant to close the
         prompt's open declaration, which we no longer need).
      2. Completion is just a body -> glue prompt + completion + tests; the
         leading `}` in tests closes the function declared in the prompt.
    """
    completion_code = _extract_code(completion).strip("\n")
    matched = _defines_function(completion_code, entry_point) or (
        original_entry_point is not None and _defines_function(completion_code, original_entry_point)
    )
    if matched:
        stripped_tests = _LEADING_CLOSE_BRACE_RE.sub("", tests, count=1)
        return completion_code, stripped_tests
    return f"{prompt.rstrip()}\n{completion_code}\n", tests


def _build_exec_script(
    candidate_program: str,
    test_code: str,
    entry_point: str,
    original_entry_point: str | None,
) -> str:
    """Concatenate program + tests + an entry-point existence guard.

    MultiPL-E tests reference the entry point by its original name. If the agent
    renamed it (via an obfuscation perturbation), we alias the renamed binding
    back to the original name before running the tests.
    """
    alias = ""
    if original_entry_point is not None and original_entry_point != entry_point:
        alias = (
            f"if (typeof {entry_point} !== 'undefined' "
            f"&& typeof {original_entry_point} === 'undefined') {{\n"
            f"  var {original_entry_point} = {entry_point};\n"
            f"}}\n"
        )
    return f"{candidate_program.rstrip()}\n{alias}{test_code}\n"


def _truncate(text: str, limit: int = 300) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "..."


def _node_executable() -> str:
    return os.environ.get("MULTIPL_E_NODE", "node")


def run_multipl_e_js_exec(case: EvalCase, timeout_seconds: float = 10.0) -> CorrectnessResult:
    """Execute one MultiPL-E JS case via Node and return binary correctness."""
    metadata: Mapping[str, object] = case.metadata
    prompt = metadata.get("prompt")
    entry_point = metadata.get("entry_point")
    original_entry_point = metadata.get("original_entry_point")
    test_code = metadata.get("test")

    if not isinstance(prompt, str) or not prompt.strip():
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=False,
            score=None,
            reason="error: missing metadata.prompt",
        )
    if not isinstance(entry_point, str) or _IDENT_RE.fullmatch(entry_point.strip()) is None:
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=False,
            score=None,
            reason="error: invalid metadata.entry_point",
        )
    if original_entry_point is not None:
        if not isinstance(original_entry_point, str) or _IDENT_RE.fullmatch(original_entry_point.strip()) is None:
            return CorrectnessResult(
                sample_id=case.sample_id,
                perturbation_name=case.perturbation_name,
                is_correct=False,
                score=None,
                reason="error: invalid metadata.original_entry_point",
            )
    if not isinstance(test_code, str) or not test_code.strip():
        return CorrectnessResult(
            sample_id=case.sample_id,
            perturbation_name=case.perturbation_name,
            is_correct=False,
            score=None,
            reason="error: missing metadata.test",
        )

    candidate_program, prepared_tests = _build_candidate_program(
        prompt, case.actual_output, entry_point, original_entry_point, test_code,
    )
    script = _build_exec_script(
        candidate_program, prepared_tests, entry_point, original_entry_point,
    )

    fd, tmp_name = tempfile.mkstemp(suffix=".js", prefix="multipl_e_")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(script)
        try:
            completed = subprocess.run(
                [_node_executable(), "--no-warnings", str(tmp_path)],
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
        except FileNotFoundError:
            return CorrectnessResult(
                sample_id=case.sample_id,
                perturbation_name=case.perturbation_name,
                is_correct=False,
                score=None,
                reason="error: node executable not found (install Node.js or set MULTIPL_E_NODE)",
            )
        except Exception as e:
            return CorrectnessResult(
                sample_id=case.sample_id,
                perturbation_name=case.perturbation_name,
                is_correct=False,
                score=None,
                reason=f"error: {e}",
            )
    finally:
        tmp_path.unlink(missing_ok=True)

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
