"""SWE-bench dataset loading and repo cloning utilities."""
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from datasets import load_dataset

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SWEBenchInstance:
    """One SWE-bench task instance."""

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    patch: str
    test_patch: str
    fail_to_pass: str
    pass_to_pass: str
    hints_text: str
    version: str


def load_skip_list(path: Path | None = None) -> set[str]:
    """Load instance IDs to skip from a YAML file."""
    if path is None:
        default = Path(__file__).resolve().parents[2] / "configs" / "swebench" / "docker_skip.yaml"
        if default.exists():
            path = default
        else:
            return set()
    import yaml
    data = yaml.safe_load(path.read_text())
    ids = set(data.get("skip_instance_ids", []))
    if ids:
        logger.info("Loaded skip list: %d instance IDs from %s", len(ids), path.name)
    return ids


def load_instances(
    dataset_name: str = "SWE-bench/SWE-bench_Verified",
    split: str = "test",
    limit: int | None = None,
    skip_ids: set[str] | None = None,
) -> list[SWEBenchInstance]:
    if skip_ids is None:
        skip_ids = load_skip_list()

    ds = load_dataset(dataset_name, split=split)
    instances = []
    skipped = 0
    for row in ds:
        iid = row["instance_id"]
        if iid in skip_ids:
            skipped += 1
            continue
        instances.append(SWEBenchInstance(
            instance_id=iid,
            repo=row["repo"],
            base_commit=row["base_commit"],
            problem_statement=row["problem_statement"],
            patch=row["patch"],
            test_patch=row["test_patch"],
            fail_to_pass=row.get("FAIL_TO_PASS", "[]"),
            pass_to_pass=row.get("PASS_TO_PASS", "[]"),
            hints_text=row.get("hints_text", ""),
            version=row.get("version", ""),
        ))
        if limit and len(instances) >= limit:
            break
    logger.info("Loaded %d instances from %s (skipped %d from skip list)",
                len(instances), dataset_name, skipped)
    return instances


def clone_repo(
    instance: SWEBenchInstance,
    work_dir: Path,
) -> Path:
    """Clone the repo at the base_commit into work_dir/{instance_id}/."""
    repo_dir = work_dir / instance.instance_id.replace("/", "__")
    if repo_dir.exists():
        logger.debug("Repo already cloned at %s", repo_dir)
        return repo_dir

    repo_url = f"https://github.com/{instance.repo}.git"
    logger.debug("Cloning %s at %s", repo_url, instance.base_commit)

    subprocess.run(
        ["git", "clone", "--quiet", repo_url, str(repo_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "checkout", "--quiet", instance.base_commit],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    logger.debug("Cloned %s -> %s", instance.repo, repo_dir)
    return repo_dir
