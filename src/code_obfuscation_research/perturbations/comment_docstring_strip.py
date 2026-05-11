"""Strip comments and Python docstrings from code artifacts."""
import ast
import io
import logging
import tokenize

import libcst as cst

from code_obfuscation_research.domain import PerturbationInput, PerturbationResult

logger = logging.getLogger(__name__)

_C_STYLE_LANGUAGES = {"java", "javascript", "js", "typescript", "ts", "c", "cpp", "c++"}


class _DocstringRemover(cst.CSTTransformer):
    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        del original_node
        return updated_node.with_changes(body=_strip_leading_docstring(updated_node.body))

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        del original_node
        return updated_node.with_changes(
            body=updated_node.body.with_changes(body=_strip_leading_docstring(updated_node.body.body))
        )

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        del original_node
        return updated_node.with_changes(
            body=updated_node.body.with_changes(body=_strip_leading_docstring(updated_node.body.body))
        )


def _is_docstring_statement(statement: cst.BaseStatement) -> bool:
    if not isinstance(statement, cst.SimpleStatementLine) or len(statement.body) != 1:
        return False
    expr = statement.body[0]
    return isinstance(expr, cst.Expr) and isinstance(expr.value, cst.SimpleString)


def _strip_leading_docstring(body: tuple[cst.BaseStatement, ...]) -> tuple[cst.BaseStatement, ...]:
    if body and _is_docstring_statement(body[0]):
        return body[1:]
    return body


def _strip_python_comments(code: str) -> str:
    tokens = tokenize.generate_tokens(io.StringIO(code).readline)
    kept = [token for token in tokens if token.type != tokenize.COMMENT]
    return tokenize.untokenize(kept)


def _strip_python(code: str) -> str:
    tree = cst.parse_module(code)
    without_docstrings = tree.visit(_DocstringRemover()).code
    without_comments = _strip_python_comments(without_docstrings)
    ast.parse(without_comments)
    return without_comments


def _strip_c_style_comments(code: str) -> str:
    result: list[str] = []
    i = 0
    in_line_comment = False
    in_block_comment = False
    in_string: str | None = None
    escaped = False

    while i < len(code):
        char = code[i]
        nxt = code[i + 1] if i + 1 < len(code) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                result.append(char)
            i += 1
            continue

        if in_block_comment:
            if char == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                if char == "\n":
                    result.append(char)
                i += 1
            continue

        if in_string is not None:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            i += 1
            continue

        if char in {"'", '"', "`"}:
            in_string = char
            result.append(char)
            i += 1
            continue

        if char == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue

        if char == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue

        result.append(char)
        i += 1

    return "".join(result)


class CommentDocstringStripPerturbation:
    """Removes comments and docstrings without changing executable code."""

    def __init__(self, name: str = "comment_docstring_strip", **_kwargs):
        self.name = name

    def apply(self, item: PerturbationInput) -> PerturbationResult:
        language = item.code.language.lower()
        original = item.code.text
        try:
            if language == "python":
                new_code = _strip_python(original)
            elif language in _C_STYLE_LANGUAGES:
                new_code = _strip_c_style_comments(original)
            else:
                return PerturbationResult(
                    perturbed_code=item.code,
                    applied=False,
                    warnings=[f"comment_docstring_strip does not support {item.code.language}"],
                )
        except (SyntaxError, cst.ParserSyntaxError, tokenize.TokenError) as e:
            return PerturbationResult(perturbed_code=item.code, applied=False, error=f"parse error: {e}")

        return PerturbationResult(
            perturbed_code=item.code.with_text(new_code),
            applied=new_code != original,
            stats={"removed_chars": len(original) - len(new_code)},
        )
