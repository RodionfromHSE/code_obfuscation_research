"""Tests for perturbation implementations."""
import ast

from code_obfuscation_research.domain import CodeArtifact, PerturbationInput
from code_obfuscation_research.perturbations.noop import NoOpPerturbation
from code_obfuscation_research.perturbations.python_rename_symbols import RenameSymbolsPerturbation


def _inp(text: str) -> PerturbationInput:
    return PerturbationInput(code=CodeArtifact(artifact_id="test", text=text))


class TestNoOp:
    def test_returns_unchanged(self):
        p = NoOpPerturbation()
        result = p.apply(_inp("def foo(): pass"))
        assert not result.applied
        assert result.perturbed_code.text == "def foo(): pass"


class TestRenameSymbols:
    def test_renames_function_to_opaque(self):
        p = RenameSymbolsPerturbation()
        result = p.apply(_inp("def foo():\n    return 1\n\nfoo()\n"))
        assert result.applied
        assert "func_0" in result.perturbed_code.text
        assert "foo" not in result.perturbed_code.text
        assert result.stats["renamed_functions"] == 1

    def test_renames_class_to_opaque(self):
        p = RenameSymbolsPerturbation()
        result = p.apply(_inp("class MyClass:\n    pass\n\nobj = MyClass()\n"))
        assert result.applied
        assert "cls_0" in result.perturbed_code.text
        assert "MyClass" not in result.perturbed_code.text
        assert result.stats["renamed_classes"] == 1

    def test_skips_private(self):
        p = RenameSymbolsPerturbation()
        result = p.apply(_inp("def _private(): pass\ndef __dunder__(): pass\n"))
        assert result.perturbed_code.text == "def _private(): pass\ndef __dunder__(): pass\n"

    def test_preserves_syntax(self):
        code = "def compute(x, y):\n    return x + y\n\nresult = compute(1, 2)\n"
        p = RenameSymbolsPerturbation()
        result = p.apply(_inp(code))
        assert result.applied
        ast.parse(result.perturbed_code.text)

    def test_handles_parse_error(self):
        p = RenameSymbolsPerturbation()
        result = p.apply(_inp("def (broken syntax"))
        assert not result.applied
        assert result.error is not None

    def test_multiple_functions(self):
        code = "def foo(): pass\ndef bar(): pass\nfoo()\nbar()\n"
        p = RenameSymbolsPerturbation()
        result = p.apply(_inp(code))
        assert result.applied
        assert result.stats["renamed_functions"] == 2
        assert "foo" not in result.perturbed_code.text
        assert "bar" not in result.perturbed_code.text
        assert "func_0" in result.perturbed_code.text
        assert "func_1" in result.perturbed_code.text

    def test_references_in_calls_renamed(self):
        code = "def greet(name):\n    return f'hi {name}'\n\nprint(greet('bob'))\n"
        p = RenameSymbolsPerturbation()
        result = p.apply(_inp(code))
        assert result.applied
        text = result.perturbed_code.text
        assert "greet" not in text
        assert "func_0" in text

    def test_original_names_fully_gone(self):
        code = "def calculate_total(items):\n    return sum(items)\n\ncalculate_total([1, 2, 3])\n"
        p = RenameSymbolsPerturbation()
        result = p.apply(_inp(code))
        assert result.applied
        assert "calculate_total" not in result.perturbed_code.text
        assert "func_0" in result.perturbed_code.text
