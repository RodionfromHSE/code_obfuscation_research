# Stages 0-3: Implementation Report

## Stage 0: Dependencies

Installed `rope==1.14.0`, `mini-swe-agent==2.2.8`, `swebench==4.1.0`.
All imports verified. Docker available (Engine 29.0.0).

## Stage 1: RepoObfuscation protocol + RepoIdentity

### Protocol (`swe_task/obfuscation/protocol.py`)

```python
class RepoObfuscation(Protocol):
    name: str
    def obfuscate(self, repo_dir: Path) -> RepoObfuscationResult: ...
```

This is the single abstraction that all obfuscation strategies implement.
Swappable via Hydra config group `repo_obfuscation` (identity | rope_rename | future ones).

### Identity (`swe_task/obfuscation/identity.py`)

Noop baseline: returns `symbols_renamed=0, files_modified=0`. Does nothing to the repo.
Used when we want to measure agent performance on unobfuscated code.

### Verification
- `isinstance(RepoIdentity(), RepoObfuscation)` -> True
- `isinstance(RopeRepoRenamer(), RepoObfuscation)` -> True
- Hydra `instantiate(cfg.repo_obfuscation)` works for both `identity` and `rope_rename` overrides.

## Stage 2: RopeRepoRenamer (cross-file rename)

### How it works

1. Opens `rope.base.project.Project(repo_dir)` 
2. Scans all `.py` files (excluding test files and setup files via `skip_patterns`)
3. Collects top-level public `def` and `class` names with their AST positions
4. For each symbol, uses `rope.refactor.rename.Rename` to rename it across the entire project
5. Rope updates ALL references: imports, attribute access, call sites, across all files
6. Safety: per-symbol 30s timeout via SIGALRM, max 200 symbols, graceful error handling

### Key fix: macOS symlink path resolution

On macOS, `/var/folders/...` and `/private/var/folders/...` refer to the same directory.
Rope resolves paths through `project.root.real_path`, but `Path.relative_to()` fails if 
the paths don't canonically match. Fixed by calling `.resolve()` on both the repo_dir 
and file paths before computing relative paths.

### Test results (10/10 passing)

- `test_renames_across_files`: renames `compute` in core.py, verifies it's updated in utils.py and __init__.py
- `test_renames_classes_across_files`: renames `DataStore` class, verifies import updates across files
- `test_skips_private_names`: `_Internal` class is NOT renamed
- `test_skips_test_file_definitions`: `test_compute` function name is NOT renamed
- `test_updates_test_file_references`: `from mypackage.core import compute` in test_core.py becomes `from mypackage.core import func_0`
- Protocol conformance tests for both Identity and RopeRepoRenamer
- Context manager: temp copy created, obfuscated, original untouched, temp cleaned up after exit

### What "cross-file" means concretely

Given this fixture:
```
mypackage/__init__.py:  from .core import compute
mypackage/core.py:      def compute(x, y): ...
mypackage/utils.py:     from .core import compute
tests/test_core.py:     from mypackage.core import compute
```

After `RopeRepoRenamer(rename_functions=True)`:
```
mypackage/__init__.py:  from .core import func_0      # updated
mypackage/core.py:      def func_0(x, y): ...          # renamed
mypackage/utils.py:     from .core import func_0       # updated  
tests/test_core.py:     from mypackage.core import func_0  # updated
```

All references updated consistently. This is what rope gives us that single-file libcst cannot.

## Stage 3: obfuscated_repo() context manager

Creates a temp copy via `shutil.copytree`, runs obfuscation in-place on the copy,
yields the result, and auto-cleans up via `tempfile.TemporaryDirectory`.

Verified: original repo is never touched. Temp directory is gone after `with` block exits.

## File structure created

```
src/swe_task/
  __init__.py
  dataset.py                      # SWE-bench instance loading + repo cloning
  pipeline.py                     # main orchestrator
  reporting.py                    # per-instance + summary reports
  obfuscation/
    __init__.py
    protocol.py                   # RepoObfuscation protocol
    identity.py                   # noop
    rope_renamer.py               # cross-file rename
    repo_copy.py                  # temp copy context manager
  agent/
    __init__.py
    runner.py                     # mini-swe-agent wrapper
  evaluation/
    __init__.py
    swebench_eval.py              # swebench harness wrapper

configs/
  repo_obfuscation/
    identity.yaml
    rope_rename.yaml
  swebench/
    default.yaml

scripts/
  run_swebench.py                 # Hydra entry point

tests/unit/swe_task/
  test_obfuscation.py             # 10 tests, all passing
```
