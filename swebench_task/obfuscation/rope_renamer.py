"""Cross-file rename of public symbols in a Python repo using rope."""
import ast
import fnmatch
import logging
import re
import signal
import threading
from dataclasses import dataclass
from pathlib import Path

from rope.base.project import Project
from rope.refactor.rename import Rename

from swebench_task.obfuscation.protocol import RepoObfuscationResult

logger = logging.getLogger(__name__)

_FUNC_PREFIX = "func_"
_CLS_PREFIX = "cls_"

_DEFAULT_IGNORED_DIRS = [
    "tests", "test", "testing",
    "docs", "doc", "examples", "example",
    "benchmarks", "benchmark",
    "build", "dist",
    ".tox", ".venv", "venv",
    "__pycache__",
]


def _reverse_rename_text(text: str, reverse_map: dict[str, str]) -> str:
    """Replace obfuscated names with originals via single-pass regex."""
    if not reverse_map:
        return text
    # longest keys first so cls_10 is matched before cls_1
    keys = sorted(reverse_map, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b")
    return pattern.sub(lambda m: reverse_map[m.group(0)], text)


class _TimeoutError(Exception):
    pass


def _signal_handler(signum: int, frame: object) -> None:
    raise _TimeoutError("rope rename timed out")


def _run_with_timeout(fn, timeout_seconds: int):
    """Run fn() with a timeout. Uses signal.alarm on main thread, no-op otherwise.

    rope's rename is CPU-bound so can't be interrupted via threading.Timer/asyncio;
    only signal can actually break in. In worker threads (e.g. async pool), we skip
    the timeout — per-instance agent timeout is the outer safety net.
    """
    if threading.current_thread() is not threading.main_thread():
        return fn()
    old_handler = signal.signal(signal.SIGALRM, _signal_handler)
    signal.alarm(timeout_seconds)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


@dataclass(frozen=True, slots=True)
class _Symbol:
    """Top-level def/class discovered by the AST scanner."""

    file_path: Path
    name: str
    kind: str  # "func" or "class"
    lineno: int  # 1-based
    col_offset: int  # 0-based byte column within the line


def _line_starts(source: str) -> list[int]:
    """Byte offset of the start of each line; last entry is end-of-file."""
    starts = [0]
    for line in source.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return starts


def _name_offset(source: str, lineno: int, col_offset: int, kind: str) -> int:
    """Byte offset of the identifier following `def ` / `class `."""
    keyword_len = len("def " if kind == "func" else "class ")
    return _line_starts(source)[lineno - 1] + col_offset + keyword_len


def _scan_file(
    file_path: Path,
    rename_functions: bool,
    rename_classes: bool,
) -> tuple[list[_Symbol], bool]:
    """Parse one .py file, return (symbols, is_syntax_error)."""
    try:
        source = file_path.read_text()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return [], True

    symbols: list[_Symbol] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and rename_functions:
            if not node.name.startswith("_"):
                symbols.append(_Symbol(file_path, node.name, "func", node.lineno, node.col_offset))
        elif isinstance(node, ast.ClassDef) and rename_classes:
            if not node.name.startswith("_"):
                symbols.append(_Symbol(file_path, node.name, "class", node.lineno, node.col_offset))
    return symbols, False


def _should_skip(file_path: Path, skip_patterns: list[str]) -> bool:
    name = file_path.name
    return any(fnmatch.fnmatch(name, pat) for pat in skip_patterns)


def _is_under_ignored_dir(
    file_path: Path, repo_dir: Path, ignored_dirs: list[str],
) -> bool:
    """True if any ancestor directory name matches one of `ignored_dirs`."""
    try:
        rel_parts = file_path.relative_to(repo_dir).parts[:-1]
    except ValueError:
        return False
    return any(part in ignored_dirs for part in rel_parts)


class RopeRepoRenamer:
    """Cross-file rename of public function/class names using rope.

    Works on the repo in-place — caller should pass a temporary copy.
    """

    def __init__(
        self,
        name: str = "rope_rename",
        rename_functions: bool = True,
        rename_classes: bool = True,
        skip_patterns: list[str] | None = None,
        ignored_dirs: list[str] | None = None,
        max_symbols: int = 200,
        per_symbol_timeout: int = 30,
    ):
        self.name = name
        self.rename_functions = rename_functions
        self.rename_classes = rename_classes
        self.skip_patterns = skip_patterns or ["test_*", "conftest*", "setup.py"]
        self.ignored_dirs = ignored_dirs if ignored_dirs is not None else list(_DEFAULT_IGNORED_DIRS)
        self.max_symbols = max_symbols
        self.per_symbol_timeout = per_symbol_timeout

    def obfuscate(self, repo_dir: Path) -> RepoObfuscationResult:
        repo_dir = repo_dir.resolve()
        symbols, bad_files = self._scan_repo(repo_dir)
        ignored_resources = list(self.ignored_dirs) + bad_files
        if bad_files:
            logger.info(
                "Found %d syntax-error files outside ignored dirs; added to rope ignored_resources",
                len(bad_files),
            )
        project = Project(str(repo_dir), ignored_resources=ignored_resources)
        try:
            return self._rename_all(project, symbols)
        finally:
            project.close()

    def deobfuscate_patch(self, patch: str, result: RepoObfuscationResult) -> str:
        """Reverse-map obfuscated names in a patch back to originals."""
        if not patch:
            return patch
        reverse = result.reverse_rename_map
        if not reverse and result.rename_map:
            # backward compat: derive reverse from forward (1:1 assumption)
            reverse = {v: k for k, v in result.rename_map.items()}
        if not reverse:
            return patch
        return _reverse_rename_text(patch, reverse)

    def _scan_repo(self, repo_dir: Path) -> tuple[list[_Symbol], list[str]]:
        """Single pass over the repo: collect symbols and list syntax-error files."""
        symbols: list[_Symbol] = []
        bad_files: list[str] = []
        for py_file in sorted(repo_dir.rglob("*.py")):
            if not py_file.is_file():
                continue
            if _is_under_ignored_dir(py_file, repo_dir, self.ignored_dirs):
                continue
            file_symbols, is_bad = _scan_file(
                py_file, self.rename_functions, self.rename_classes,
            )
            if is_bad:
                bad_files.append(str(py_file.relative_to(repo_dir)))
                continue
            if _should_skip(py_file, self.skip_patterns):
                continue
            symbols.extend(file_symbols)
        return symbols, bad_files

    def _rename_all(
        self, project: Project, symbols: list[_Symbol],
    ) -> RepoObfuscationResult:
        if len(symbols) > self.max_symbols:
            logger.warning(
                "Found %d symbols, capping at max_symbols=%d",
                len(symbols), self.max_symbols,
            )
            symbols = symbols[: self.max_symbols]

        func_counter = 0
        cls_counter = 0
        rename_map: dict[str, str] = {}
        reverse_rename_map: dict[str, str] = {}
        errors: list[str] = []
        skipped: list[str] = []
        modified_files: set[str] = set()

        for sym in symbols:
            if sym.kind == "func":
                new_name = f"{_FUNC_PREFIX}{func_counter}"
                func_counter += 1
            else:
                new_name = f"{_CLS_PREFIX}{cls_counter}"
                cls_counter += 1

            try:
                changed_files = self._do_rename(project, sym, new_name)
                rename_map[sym.name] = new_name
                reverse_rename_map[new_name] = sym.name
                modified_files.update(changed_files)
                logger.debug(
                    "Renamed %s -> %s (%d files touched)",
                    sym.name, new_name, len(changed_files),
                )
            except _TimeoutError:
                skipped.append(f"{sym.name}: timeout ({self.per_symbol_timeout}s)")
                logger.warning("Timeout renaming %s in %s", sym.name, sym.file_path)
            except Exception as e:
                errors.append(f"{sym.name} in {sym.file_path.name}: {e}")
                logger.warning("Failed to rename %s in %s: %s", sym.name, sym.file_path, e)

        return RepoObfuscationResult(
            symbols_renamed=len(reverse_rename_map),
            files_modified=len(modified_files),
            rename_map=rename_map,
            reverse_rename_map=reverse_rename_map,
            errors=errors,
            skipped=skipped,
        )

    def _do_rename(
        self, project: Project, sym: _Symbol, new_name: str,
    ) -> list[str]:
        """Rename one symbol across the project. Returns list of changed file paths."""
        project_root = Path(project.root.real_path).resolve()
        rel_path = str(sym.file_path.relative_to(project_root))
        resource = project.get_resource(rel_path)

        offset = _name_offset(resource.read(), sym.lineno, sym.col_offset, sym.kind)
        renamer = Rename(project, resource, offset)

        def _apply():
            changes = renamer.get_changes(new_name)
            project.do(changes)
            return changes

        changes = _run_with_timeout(_apply, self.per_symbol_timeout)
        return [c.resource.path for c in changes.changes]
