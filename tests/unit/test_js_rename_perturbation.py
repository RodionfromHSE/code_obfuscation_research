"""Tests for the JavaScript rename-symbols perturbation."""
from code_obfuscation_research.domain import CodeArtifact, PerturbationInput
from code_obfuscation_research.perturbations.js_rename_symbols import (
    RenameSymbolsJSPerturbation,
)


def _apply(perturbation: RenameSymbolsJSPerturbation, code: str):
    return perturbation.apply(
        PerturbationInput(
            code=CodeArtifact(artifact_id="t", text=code, language="javascript"),
            sample_id="t",
        )
    )


def test_renames_function_declaration():
    pert = RenameSymbolsJSPerturbation()
    result = _apply(pert, "function add(a, b) {\n  return a + b;\n}\n")
    assert result.applied is True
    assert "function func_0(a, b)" in result.perturbed_code.text
    assert result.stats["renamed_function_map"] == {"add": "func_0"}


def test_renames_recursive_call():
    pert = RenameSymbolsJSPerturbation()
    src = "function fact(n) {\n  return n <= 1 ? 1 : fact(n - 1) * n;\n}\n"
    result = _apply(pert, src)
    assert "function func_0" in result.perturbed_code.text
    assert "func_0(n - 1)" in result.perturbed_code.text
    assert "fact" not in result.perturbed_code.text


def test_string_contents_are_not_renamed():
    pert = RenameSymbolsJSPerturbation()
    src = 'function foo() {\n  return "foo is the answer";\n}\n'
    result = _apply(pert, src)
    text = result.perturbed_code.text
    assert "function func_0()" in text
    assert '"foo is the answer"' in text


def test_comments_are_not_renamed():
    pert = RenameSymbolsJSPerturbation()
    src = "// add(1, 2) returns 3\nfunction add(a, b) {\n  return a + b;\n}\n"
    result = _apply(pert, src)
    text = result.perturbed_code.text
    assert "// add(1, 2) returns 3" in text
    assert "function func_0(a, b)" in text


def test_underscore_prefixed_names_are_skipped():
    pert = RenameSymbolsJSPerturbation()
    src = "function _internal(x) {\n  return x;\n}\nfunction add(x) {\n  return _internal(x);\n}\n"
    result = _apply(pert, src)
    text = result.perturbed_code.text
    assert "function _internal" in text  # untouched
    assert "function func_0(x)" in text  # add -> func_0
    assert "return _internal(x)" in text  # call site preserved


def test_multiple_functions_get_distinct_placeholders():
    pert = RenameSymbolsJSPerturbation()
    src = (
        "function helper(x) { return x + 1; }\n"
        "function main(y) { return helper(y) * 2; }\n"
    )
    result = _apply(pert, src)
    mapping = result.stats["renamed_function_map"]
    assert mapping == {"helper": "func_0", "main": "func_1"}
    text = result.perturbed_code.text
    assert "function func_0(x)" in text
    assert "function func_1(y)" in text
    assert "func_0(y)" in text


def test_classes_renamed():
    pert = RenameSymbolsJSPerturbation(rename_functions=False, rename_classes=True)
    src = "class Foo {\n  m() { return new Foo(); }\n}\n"
    result = _apply(pert, src)
    text = result.perturbed_code.text
    assert "class cls_0" in text
    assert "new cls_0()" in text


def test_parameter_rename_only():
    pert = RenameSymbolsJSPerturbation(
        rename_functions=False, rename_classes=False, rename_parameters=True,
    )
    src = "function add(a, b) {\n  return a + b;\n}\n"
    result = _apply(pert, src)
    text = result.perturbed_code.text
    assert "function add(arg_0, arg_1)" in text
    assert "return arg_0 + arg_1;" in text
    assert result.stats["renamed_parameter_map"] == {"a": "arg_0", "b": "arg_1"}


def test_parameter_rename_strips_default_values():
    pert = RenameSymbolsJSPerturbation(
        rename_functions=False, rename_parameters=True,
    )
    src = "function f(x = 1, y = 2) { return x + y; }\n"
    result = _apply(pert, src)
    text = result.perturbed_code.text
    assert "function f(arg_0 = 1, arg_1 = 2)" in text
    assert "return arg_0 + arg_1;" in text


def test_function_and_parameter_rename_combined():
    pert = RenameSymbolsJSPerturbation(rename_parameters=True)
    src = "function add(a, b) { return a + b; }\n"
    result = _apply(pert, src)
    text = result.perturbed_code.text
    assert "function func_0(arg_0, arg_1)" in text
    assert "return arg_0 + arg_1;" in text


def test_no_match_returns_not_applied():
    pert = RenameSymbolsJSPerturbation()
    src = "// just a comment\n"
    result = _apply(pert, src)
    assert result.applied is False
    assert result.perturbed_code.text == src


def test_multipl_e_style_incomplete_prompt():
    pert = RenameSymbolsJSPerturbation()
    src = (
        "// Check if list has close elements\n"
        "// >>> has_close_elements([1.0, 2.0, 3.0], 0.5)\n"
        "function has_close_elements(numbers, threshold) {\n"
    )
    result = _apply(pert, src)
    text = result.perturbed_code.text
    assert "function func_0(numbers, threshold) {" in text
    assert "has_close_elements" in text  # in comment, untouched
    assert result.stats["renamed_function_map"] == {"has_close_elements": "func_0"}
