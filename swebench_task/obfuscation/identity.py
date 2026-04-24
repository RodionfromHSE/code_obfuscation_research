"""Identity (noop) obfuscation: returns repo unchanged."""
from pathlib import Path

from swebench_task.obfuscation.protocol import RepoObfuscationResult


class RepoIdentity:
    """Baseline: no obfuscation applied."""

    def __init__(self, name: str = "identity"):
        self.name = name

    def obfuscate(self, repo_dir: Path) -> RepoObfuscationResult:
        del repo_dir
        return RepoObfuscationResult(symbols_renamed=0, files_modified=0)

    def deobfuscate_patch(self, patch: str, result: RepoObfuscationResult) -> str:
        return patch
