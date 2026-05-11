"""Tests for deterministic MultiPL-E JavaScript execution evaluator."""
import shutil

import pytest

from code_obfuscation_research.domain import EvalCase
from code_obfuscation_research.evaluation.multipl_e_js_exec import (
    _build_candidate_program,
    _defines_function,
    run_multipl_e_js_exec,
)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node not available on PATH",
)

_PROMPT = (
    "// Add two numbers.\n"
    "function add(a, b) {\n"
)

# MultiPL-E-style tests: leading `}` closes the prompt's open declaration.
_TESTS = (
    "}\n"
    "const assert = require('node:assert');\n"
    "const candidate = add;\n"
    "assert.strictEqual(candidate(1, 2), 3);\n"
    "assert.strictEqual(candidate(10, -3), 7);\n"
)


def _make_case(actual_output: str, original_entry_point: str | None = None) -> EvalCase:
    metadata: dict = {
        "prompt": _PROMPT,
        "entry_point": "add",
        "test": _TESTS,
        "language": "javascript",
        "task_type": "multipl_e_humaneval_js",
    }
    if original_entry_point is not None:
        metadata["original_entry_point"] = original_entry_point
    return EvalCase(
        sample_id="HumanEval_0_add",
        input_text=_PROMPT,
        actual_output=actual_output,
        expected_output="",
        perturbation_name="noop",
        metadata=metadata,
    )


def test_pass_with_body_only_completion():
    case = _make_case("    return a + b;")
    result = run_multipl_e_js_exec(case, timeout_seconds=5.0)
    assert result.is_correct is True
    assert result.score == 1.0
    assert result.reason == "passed"


def test_pass_with_full_function_completion():
    completion = "function add(a, b) {\n  return a + b;\n}\n"
    case = _make_case(completion)
    result = run_multipl_e_js_exec(case, timeout_seconds=5.0)
    assert result.is_correct is True
    assert result.score == 1.0


def test_pass_with_arrow_function_completion():
    completion = "const add = (a, b) => a + b;\n"
    case = _make_case(completion)
    result = run_multipl_e_js_exec(case, timeout_seconds=5.0)
    assert result.is_correct is True


def test_pass_with_markdown_fence():
    completion = "```javascript\nfunction add(a, b) { return a + b; }\n```"
    case = _make_case(completion)
    result = run_multipl_e_js_exec(case, timeout_seconds=5.0)
    assert result.is_correct is True


def test_fail_case():
    case = _make_case("    return a - b;")
    result = run_multipl_e_js_exec(case, timeout_seconds=5.0)
    assert result.is_correct is False
    assert result.score == 0.0


def test_renamed_entry_point_aliased_back():
    completion = "function arg_0(a, b) { return a + b; }"
    case = _make_case(completion, original_entry_point="add")
    # entry_point reflects the renamed symbol, original_entry_point is what tests look for
    case = EvalCase(
        sample_id=case.sample_id,
        input_text=case.input_text,
        actual_output=case.actual_output,
        expected_output=case.expected_output,
        perturbation_name=case.perturbation_name,
        metadata={**case.metadata, "entry_point": "arg_0", "original_entry_point": "add"},
    )
    result = run_multipl_e_js_exec(case, timeout_seconds=5.0)
    assert result.is_correct is True


def test_missing_metadata_is_error():
    case = EvalCase(
        sample_id="X",
        input_text="",
        actual_output="return a + b;",
        expected_output="",
        perturbation_name="noop",
        metadata={},
    )
    result = run_multipl_e_js_exec(case, timeout_seconds=2.0)
    assert result.is_correct is False
    assert result.score is None


def test_build_candidate_program_strips_leading_brace_when_full_function():
    program, tests = _build_candidate_program(
        prompt=_PROMPT,
        completion="function add(a, b) { return a + b; }",
        entry_point="add",
        original_entry_point=None,
        tests=_TESTS,
    )
    assert program.startswith("function add")
    assert not tests.lstrip().startswith("}")


def test_build_candidate_program_glues_body_with_prompt():
    program, tests = _build_candidate_program(
        prompt=_PROMPT,
        completion="    return a + b;",
        entry_point="add",
        original_entry_point=None,
        tests=_TESTS,
    )
    assert "function add(a, b) {" in program
    assert tests == _TESTS  # leading `}` preserved


def test_defines_function_detects_forms():
    assert _defines_function("function add(a, b) {}", "add")
    assert _defines_function("const add = (a, b) => a + b;", "add")
    assert _defines_function("let add = function(a, b) { return a + b; }", "add")
    assert not _defines_function("return add(1, 2);", "add")
    assert not _defines_function("// add two numbers", "add")
