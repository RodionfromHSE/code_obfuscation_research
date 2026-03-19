"""Rename function/class names to opaque placeholders using libcst."""
import ast
import logging

import libcst as cst

from code_obfuscation_research.domain import PerturbationInput, PerturbationResult

logger = logging.getLogger(__name__)


class _NameMapper:
    """Maps original names to opaque placeholders like func_0, func_1, cls_0, cls_1."""

    def __init__(self, prefix: str):
        self._prefix = prefix
        self._counter = 0
        self._mapping: dict[str, str] = {}

    def get_or_create(self, original: str) -> str:
        if original not in self._mapping:
            self._mapping[original] = f"{self._prefix}{self._counter}"
            self._counter += 1
        return self._mapping[original]

    @property
    def mapping(self) -> dict[str, str]:
        return self._mapping


class _SymbolRenamer(cst.CSTTransformer):
    """Renames function and class definitions and all their references."""

    def __init__(self, rename_functions: bool, rename_classes: bool):
        super().__init__()
        self.func_map = _NameMapper("func_") if rename_functions else None
        self.class_map = _NameMapper("cls_") if rename_classes else None

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        if self.func_map is None:
            return updated_node
        old_name = updated_node.name.value
        if old_name.startswith("_"):
            return updated_node
        new_name = self.func_map.get_or_create(old_name)
        return updated_node.with_changes(name=cst.Name(new_name))

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        if self.class_map is None:
            return updated_node
        old_name = updated_node.name.value
        if old_name.startswith("_"):
            return updated_node
        new_name = self.class_map.get_or_create(old_name)
        return updated_node.with_changes(name=cst.Name(new_name))

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        name = updated_node.value
        if self.func_map and name in self.func_map.mapping:
            return updated_node.with_changes(value=self.func_map.mapping[name])
        if self.class_map and name in self.class_map.mapping:
            return updated_node.with_changes(value=self.class_map.mapping[name])
        return updated_node

    def leave_Attribute(self, original_node: cst.Attribute, updated_node: cst.Attribute) -> cst.Attribute:
        attr = updated_node.attr
        if isinstance(attr, cst.Name):
            name = attr.value
            if self.func_map and name in self.func_map.mapping:
                return updated_node.with_changes(attr=cst.Name(self.func_map.mapping[name]))
            if self.class_map and name in self.class_map.mapping:
                return updated_node.with_changes(attr=cst.Name(self.class_map.mapping[name]))
        return updated_node

    @property
    def stats(self) -> dict[str, int]:
        s: dict[str, int] = {}
        if self.func_map:
            s["renamed_functions"] = len(self.func_map.mapping)
        if self.class_map:
            s["renamed_classes"] = len(self.class_map.mapping)
        return s


def _validate_syntax(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


class RenameSymbolsPerturbation:
    """Replaces function/class names with opaque placeholders (func_0, cls_0, etc.)."""

    def __init__(
        self,
        name: str = "rename_symbols",
        rename_functions: bool = True,
        rename_classes: bool = True,
        rename_variables: bool = False,
        **_kwargs,
    ):
        self.name = name
        self.rename_functions = rename_functions
        self.rename_classes = rename_classes
        self.rename_variables = rename_variables

    def apply(self, item: PerturbationInput) -> PerturbationResult:
        original_text = item.code.text
        try:
            tree = cst.parse_module(original_text)
        except cst.ParserSyntaxError as e:
            return PerturbationResult(
                perturbed_code=item.code,
                applied=False,
                error=f"parse error: {e}",
            )

        renamer = _SymbolRenamer(
            rename_functions=self.rename_functions,
            rename_classes=self.rename_classes,
        )
        new_tree = tree.visit(renamer)
        new_code = new_tree.code

        if not _validate_syntax(new_code):
            return PerturbationResult(
                perturbed_code=item.code,
                applied=False,
                error="post-perturbation syntax validation failed",
                warnings=["generated code has syntax errors"],
            )

        return PerturbationResult(
            perturbed_code=item.code.with_text(new_code),
            applied=True,
            stats=renamer.stats,
        )
