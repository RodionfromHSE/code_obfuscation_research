"""Cross-file rename of public symbols in a Python repo using rope."""
import ast
import fnmatch
import logging
import re
import signal
from pathlib import Path

from rope.base.project import Project
from rope.refactor.rename import Rename

from swe_task.obfuscation.protocol import RepoObfuscationResult

logger = logging.getLogger(__name__)

_FUNC_PREFIX = "func_"
_CLS_PREFIX = "cls_"


def _reverse_rename_text(text: str, rename_map: dict[str, str]) -> str:
    """Replace obfuscated names with originals via single-pass regex."""
    reverse = {v: k for k, v in rename_map.items()}
    if not reverse:
        return text
    # longest keys first so cls_10 is matched before cls_1
    keys = sorted(reverse, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b")
    return pattern.sub(lambda m: reverse[m.group(0)], text)


class _TimeoutError(Exception):
    pass


def _timeout_handler(signum: int, frame: object) -> None:
    raise _TimeoutError("rope rename timed out")


def _collect_public_symbols(
    file_path: Path,
    rename_functions: bool,
    rename_classes: bool,
) -> list[tuple[str, str, int]]:
    """Parse a file and return (name, kind, offset) for each public top-level def/class."""
    try:
        source = file_path.read_text()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []

    symbols: list[tuple[str, str, int]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and rename_functions:
            if not node.name.startswith("_"):
                symbols.append((node.name, "func", node.col_offset))
        elif isinstance(node, ast.ClassDef) and rename_classes:
            if not node.name.startswith("_"):
                symbols.append((node.name, "class", node.col_offset))
    return symbols


def _should_skip(file_path: Path, skip_patterns: list[str]) -> bool:
    name = file_path.name
    return any(fnmatch.fnmatch(name, pat) for pat in skip_patterns)


def _find_offset(source: str, name: str, hint_col: int) -> int | None:
    """Find the byte offset of a top-level symbol definition in source."""
    for i, line in enumerate(source.splitlines(keepends=True)):
        stripped = line.lstrip()
        if stripped.startswith(f"def {name}") or stripped.startswith(f"class {name}"):
            idx = line.index(name)
            offset = sum(len(ln) for ln in source.splitlines(keepends=True)[:i]) + idx
            return offset
    return None


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
        max_symbols: int = 200,
        per_symbol_timeout: int = 30,
    ):
        self.name = name
        self.rename_functions = rename_functions
        self.rename_classes = rename_classes
        self.skip_patterns = skip_patterns or ["test_*", "conftest*", "setup.py"]
        self.max_symbols = max_symbols
        self.per_symbol_timeout = per_symbol_timeout

    def obfuscate(self, repo_dir: Path) -> RepoObfuscationResult:
        repo_dir = repo_dir.resolve()
        project = Project(str(repo_dir))
        try:
            return self._obfuscate_project(project, repo_dir)
        finally:
            project.close()

    def deobfuscate_patch(self, patch: str, result: RepoObfuscationResult) -> str:
        """Reverse-map obfuscated names in a patch back to originals."""
        if not patch or not result.rename_map:
            return patch
        return _reverse_rename_text(patch, result.rename_map)

    def _obfuscate_project(self, project: Project, repo_dir: Path) -> RepoObfuscationResult:
        all_symbols = self._collect_all_symbols(repo_dir)
        if len(all_symbols) > self.max_symbols:
            logger.warning(
                "Found %d symbols, capping at max_symbols=%d",
                len(all_symbols), self.max_symbols,
            )
            all_symbols = all_symbols[: self.max_symbols]

        func_counter = 0
        cls_counter = 0
        rename_map: dict[str, str] = {}
        errors: list[str] = []
        skipped: list[str] = []
        modified_files: set[str] = set()

        for file_path, sym_name, kind, col_offset in all_symbols:
            if sym_name in rename_map:
                skipped.append(f"{sym_name}: already renamed")
                continue

            if kind == "func":
                new_name = f"{_FUNC_PREFIX}{func_counter}"
                func_counter += 1
            else:
                new_name = f"{_CLS_PREFIX}{cls_counter}"
                cls_counter += 1

            try:
                changed_files = self._do_rename(
                    project, file_path, sym_name, new_name, col_offset,
                )
                rename_map[sym_name] = new_name
                modified_files.update(changed_files)
                logger.debug("Renamed %s -> %s (%d files touched)", sym_name, new_name, len(changed_files))
            except _TimeoutError:
                skipped.append(f"{sym_name}: timeout ({self.per_symbol_timeout}s)")
                logger.warning("Timeout renaming %s in %s", sym_name, file_path)
            except Exception as e:
                errors.append(f"{sym_name} in {file_path.name}: {e}")
                logger.warning("Failed to rename %s in %s: %s", sym_name, file_path, e)

        return RepoObfuscationResult(
            symbols_renamed=len(rename_map),
            files_modified=len(modified_files),
            rename_map=rename_map,
            errors=errors,
            skipped=skipped,
        )

    def _collect_all_symbols(
        self, repo_dir: Path,
    ) -> list[tuple[Path, str, str, int]]:
        """Collect (file_path, name, kind, col_offset) across the repo."""
        results: list[tuple[Path, str, str, int]] = []
        seen_names: set[str] = set()

        for py_file in sorted(repo_dir.rglob("*.py")):
            if _should_skip(py_file, self.skip_patterns):
                continue
            if not py_file.is_file():
                continue
            symbols = _collect_public_symbols(
                py_file, self.rename_functions, self.rename_classes,
            )
            for name, kind, col in symbols:
                if name not in seen_names:
                    results.append((py_file, name, kind, col))
                    seen_names.add(name)
        return results

    def _do_rename(
        self,
        project: Project,
        file_path: Path,
        sym_name: str,
        new_name: str,
        hint_col: int,
    ) -> list[str]:
        """Rename one symbol across the project. Returns list of changed file paths."""
        project_root = Path(project.root.real_path).resolve()
        rel_path = str(file_path.resolve().relative_to(project_root))
        resource = project.get_resource(rel_path)

        source = resource.read()
        offset = _find_offset(source, sym_name, hint_col)
        if offset is None:
            raise ValueError(f"Could not find '{sym_name}' definition in {rel_path}")

        renamer = Rename(project, resource, offset)

        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(self.per_symbol_timeout)
        try:
            changes = renamer.get_changes(new_name)
            project.do(changes)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

        changed = []
        for change in changes.changes:
            changed.append(change.resource.path)
        return changed
