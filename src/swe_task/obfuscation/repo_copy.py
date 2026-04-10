"""Context manager that creates a temporary obfuscated copy of a repo."""
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from swe_task.obfuscation.protocol import RepoObfuscation, RepoObfuscationResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ObfuscatedRepoContext:
    """Holds paths and stats for an obfuscated repo copy."""

    original_dir: Path
    obfuscated_dir: Path
    result: RepoObfuscationResult


def _git_commit_obfuscation(repo_dir: Path) -> None:
    """Stage and commit all obfuscation changes so git diff only shows the agent's work."""
    if not (repo_dir / ".git").exists():
        return
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.name=obfuscator", "-c", "user.email=noreply@obfus",
         "commit", "-m", "obfuscation", "--allow-empty", "--quiet"],
        cwd=repo_dir, capture_output=True, check=True,
    )


@contextmanager
def obfuscated_repo(
    repo_dir: Path,
    obfuscation: RepoObfuscation,
) -> Iterator[ObfuscatedRepoContext]:
    """Copy repo to tempdir, obfuscate in-place, commit, yield context, cleanup on exit."""
    with tempfile.TemporaryDirectory(prefix="obfus_") as tmp:
        copy_dir = Path(tmp) / repo_dir.name
        shutil.copytree(repo_dir, copy_dir, symlinks=True)
        logger.debug("Created temp copy at %s", copy_dir)

        result = obfuscation.obfuscate(copy_dir)
        logger.debug(
            "Obfuscation '%s': %d symbols renamed, %d files modified, %d errors",
            obfuscation.name, result.symbols_renamed, result.files_modified, len(result.errors),
        )

        _git_commit_obfuscation(copy_dir)

        yield ObfuscatedRepoContext(
            original_dir=repo_dir,
            obfuscated_dir=copy_dir,
            result=result,
        )
    logger.debug("Cleaned up temp copy for %s", repo_dir.name)
