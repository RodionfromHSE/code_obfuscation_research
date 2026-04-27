"""Protocol for repo-level obfuscation strategies."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RepoObfuscationResult:
    """Outcome of obfuscating a repository.

    `rename_map` is `old -> new`. When two files both define `foo` at module
    level, each gets its own distinct new name (e.g. `func_0`, `func_1`), and
    `rename_map["foo"]` holds the last-renamed one — use `reverse_rename_map`
    (`new -> old`, always 1:1) for deobfuscation.
    """

    symbols_renamed: int
    files_modified: int
    rename_map: dict[str, str] = field(default_factory=dict)
    reverse_rename_map: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@runtime_checkable
class RepoObfuscation(Protocol):
    """Pluggable repo-level obfuscation strategy (swappable via Hydra)."""

    name: str

    def obfuscate(self, repo_dir: Path) -> RepoObfuscationResult:
        """Obfuscate the repo in-place. Caller is responsible for working on a copy."""
        ...

    def deobfuscate_patch(self, patch: str, result: RepoObfuscationResult) -> str:
        """Reverse-map an agent patch from obfuscated names back to original names."""
        ...
