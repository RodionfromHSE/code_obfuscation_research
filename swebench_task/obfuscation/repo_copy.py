"""Context manager that creates a temporary obfuscated copy of a repo."""
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from swebench_task.obfuscation.protocol import RepoObfuscation, RepoObfuscationResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ObfuscatedRepoContext:
    """Holds paths and stats for an obfuscated repo copy."""

    obfuscated_dir: Path
    result: RepoObfuscationResult


def _clone_local(src: Path, dst: Path) -> None:
    """Fast duplicate of a git working tree.

    `git clone --local` hardlinks `.git/objects` on the same filesystem, so
    large repos (django/sklearn) copy in a fraction of a second vs seconds
    with `shutil.copytree`. The hardlinked objects dir is safe because we
    never mutate source history; new commits made in dst write fresh
    (non-hardlinked) objects.

    Falls back to shutil.copytree when src isn't a git repo.
    """
    if not (src / ".git").exists():
        shutil.copytree(src, dst, symlinks=True)
        return
    clone_cmd = ["git", "clone", "--local", "--quiet"]
    if _cross_fs(src, dst.parent):
        clone_cmd.append("--no-hardlinks")
    clone_cmd += [str(src), str(dst)]
    subprocess.run(clone_cmd, check=True, capture_output=True)


def _cross_fs(a: Path, b: Path) -> bool:
    """True if a and b are on different filesystems (hardlinks impossible)."""
    try:
        return a.stat().st_dev != b.stat().st_dev
    except OSError:
        return True


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
    """Clone repo to tempdir, obfuscate in-place, commit, yield context, cleanup on exit."""
    with tempfile.TemporaryDirectory(prefix="obfus_") as tmp:
        copy_dir = Path(tmp) / repo_dir.name
        _clone_local(repo_dir, copy_dir)
        logger.debug("Created temp copy at %s", copy_dir)

        result = obfuscation.obfuscate(copy_dir)
        logger.debug(
            "Obfuscation '%s': %d symbols renamed, %d files modified, %d errors",
            obfuscation.name, result.symbols_renamed, result.files_modified, len(result.errors),
        )

        _git_commit_obfuscation(copy_dir)

        yield ObfuscatedRepoContext(obfuscated_dir=copy_dir, result=result)
    logger.debug("Cleaned up temp copy for %s", repo_dir.name)
