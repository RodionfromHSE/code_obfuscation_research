"""Rename top-level function/class names (and optionally parameters) in JavaScript code.

Regex-based on purpose — Babel isn't required at runtime. This is accurate
enough for MultiPL-E HumanEval-JS prompts (no nested scopes, no destructuring,
no template-literal `${}` interpolation that overlaps with identifiers we
rename, no regex literals). For richer JS sources, switch to an AST-based
renamer (e.g. via Babel through a Node helper).

Emits the same `renamed_function_map` / `renamed_class_map` /
`renamed_parameter_map` stats keys that the Python renamer uses, so
`_remap_humaneval_entry_point_if_needed` in the run pipeline rewires the
entry-point metadata automatically.
"""
import re

from code_obfuscation_research.domain import PerturbationInput, PerturbationResult

# One tokenizer pass over the source. Each alternative consumes a comment,
# a string literal, or a single identifier. Only the identifier branch
# captures into `ident`; comments/strings pass through unchanged.
_JS_TOKEN_RE = re.compile(
    r"""
    //[^\n]*                            # single-line comment
    | /\*[\s\S]*?\*/                    # block comment
    | "(?:\\.|[^"\\])*"                 # double-quoted string
    | '(?:\\.|[^'\\])*'                 # single-quoted string
    | `(?:\\.|[^`\\])*`                 # template literal (simplified)
    | \b(?P<ident>[A-Za-z_$][A-Za-z0-9_$]*)\b
    """,
    re.VERBOSE,
)

_FUNCTION_DECL_RE = re.compile(
    r"^[ \t]*(?:async\s+)?function\s*\*?\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
    re.MULTILINE,
)
_CLASS_DECL_RE = re.compile(
    r"^[ \t]*class\s+([A-Za-z_$][A-Za-z0-9_$]*)\b",
    re.MULTILINE,
)
_PARAM_SIG_RE = re.compile(
    r"^[ \t]*(?:async\s+)?function\s*\*?\s*[A-Za-z_$][A-Za-z0-9_$]*\s*\((?P<params>[^)]*)\)",
    re.MULTILINE,
)
_PARAM_RESERVED = frozenset({"this", "arguments"})


class _Counter:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.mapping: dict[str, str] = {}

    def add(self, name: str) -> str:
        if name not in self.mapping:
            self.mapping[name] = f"{self.prefix}{len(self.mapping)}"
        return self.mapping[name]


def _find_top_level_names(code: str, pattern: re.Pattern[str]) -> list[str]:
    """Return distinct top-level declarations in source order, skipping `_`-prefixed."""
    seen: set[str] = set()
    out: list[str] = []
    for match in pattern.finditer(code):
        name = match.group(1)
        if name.startswith("_") or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _find_parameter_names(code: str) -> list[str]:
    """Return distinct parameter identifiers across all top-level function signatures.

    Strips default values (`x = 1`) and skips destructured forms — HumanEval-JS
    prompts use only positional identifier params, so a richer parser is
    overkill here.
    """
    seen: set[str] = set()
    out: list[str] = []
    for match in _PARAM_SIG_RE.finditer(code):
        for raw in match.group("params").split(","):
            ident = raw.strip().split("=")[0].strip()
            if not ident or ident.startswith("_") or ident in _PARAM_RESERVED:
                continue
            if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", ident):
                continue
            if ident in seen:
                continue
            seen.add(ident)
            out.append(ident)
    return out


def _replace_outside_strings_and_comments(code: str, name_map: dict[str, str]) -> str:
    if not name_map:
        return code

    def repl(match: re.Match[str]) -> str:
        ident = match.group("ident")
        if ident is not None and ident in name_map:
            return name_map[ident]
        return match.group(0)

    return _JS_TOKEN_RE.sub(repl, code)


class RenameSymbolsJSPerturbation:
    """Replaces JS function/class names (and optionally parameters) with placeholders.

    func_0, func_1, ... for functions; cls_0, cls_1, ... for classes;
    arg_0, arg_1, ... for parameters. Names starting with `_` are skipped.
    """

    def __init__(
        self,
        name: str = "rename_symbols_js",
        rename_functions: bool = True,
        rename_classes: bool = True,
        rename_parameters: bool = False,
        **_kwargs,
    ):
        self.name = name
        self.rename_functions = rename_functions
        self.rename_classes = rename_classes
        self.rename_parameters = rename_parameters

    def apply(self, item: PerturbationInput) -> PerturbationResult:
        code = item.code.text

        func_counter = _Counter("func_") if self.rename_functions else None
        class_counter = _Counter("cls_") if self.rename_classes else None
        param_counter = _Counter("arg_") if self.rename_parameters else None

        merged: dict[str, str] = {}

        if func_counter is not None:
            for n in _find_top_level_names(code, _FUNCTION_DECL_RE):
                func_counter.add(n)
            merged.update(func_counter.mapping)

        if class_counter is not None:
            for n in _find_top_level_names(code, _CLASS_DECL_RE):
                class_counter.add(n)
            merged.update(class_counter.mapping)

        if param_counter is not None:
            for n in _find_parameter_names(code):
                # avoid colliding with function/class renames
                if n in merged:
                    continue
                param_counter.add(n)
            merged.update(param_counter.mapping)

        new_code = _replace_outside_strings_and_comments(code, merged)

        stats: dict[str, object] = {}
        if func_counter is not None:
            stats["renamed_functions"] = len(func_counter.mapping)
            stats["renamed_function_map"] = dict(func_counter.mapping)
        if class_counter is not None:
            stats["renamed_classes"] = len(class_counter.mapping)
            stats["renamed_class_map"] = dict(class_counter.mapping)
        if param_counter is not None:
            stats["renamed_parameters"] = len(param_counter.mapping)
            stats["renamed_parameter_map"] = dict(param_counter.mapping)

        return PerturbationResult(
            perturbed_code=item.code.with_text(new_code),
            applied=bool(merged),
            stats=stats,
        )
