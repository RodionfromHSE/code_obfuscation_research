"""Insert unreachable Python code while preserving syntax."""
import ast
import logging

import libcst as cst

from code_obfuscation_research.domain import PerturbationInput, PerturbationResult

logger = logging.getLogger(__name__)

_DEAD_CODE = "if False:\n    __obfuscation_dead_code = 'unused'\n"


def _is_module_docstring(statement: cst.BaseStatement) -> bool:
    if not isinstance(statement, cst.SimpleStatementLine) or len(statement.body) != 1:
        return False
    expr = statement.body[0]
    return isinstance(expr, cst.Expr) and isinstance(expr.value, cst.SimpleString)


def _is_future_import(statement: cst.BaseStatement) -> bool:
    if not isinstance(statement, cst.SimpleStatementLine) or len(statement.body) != 1:
        return False
    item = statement.body[0]
    return (
        isinstance(item, cst.ImportFrom)
        and item.module is not None
        and item.module.deep_equals(cst.Name("__future__"))
    )


def _insertion_index(body: list[cst.BaseStatement]) -> int:
    index = 0
    if body and _is_module_docstring(body[0]):
        index = 1
    while index < len(body) and _is_future_import(body[index]):
        index += 1
    return index


class DeadCodeInsertionPerturbation:
    """Adds a top-level unreachable block to Python code."""

    def __init__(self, name: str = "dead_code_insertion", **_kwargs):
        self.name = name

    def apply(self, item: PerturbationInput) -> PerturbationResult:
        if item.code.language.lower() != "python":
            return PerturbationResult(
                perturbed_code=item.code,
                applied=False,
                warnings=[f"dead_code_insertion supports python, got {item.code.language}"],
            )

        try:
            tree = cst.parse_module(item.code.text)
            dead_code = cst.parse_statement(_DEAD_CODE)
        except cst.ParserSyntaxError as e:
            return PerturbationResult(perturbed_code=item.code, applied=False, error=f"parse error: {e}")

        body = list(tree.body)
        body.insert(_insertion_index(body), dead_code)
        new_code = tree.with_changes(body=body).code

        try:
            ast.parse(new_code)
        except SyntaxError as e:
            return PerturbationResult(
                perturbed_code=item.code,
                applied=False,
                error=f"post-perturbation syntax validation failed: {e}",
            )

        return PerturbationResult(
            perturbed_code=item.code.with_text(new_code),
            applied=True,
            stats={"inserted_dead_blocks": 1},
        )
