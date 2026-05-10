"""SWE-bench dataset loading and repo cloning utilities."""
import logging
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml
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


def _configs_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "configs"


def load_skip_list(path: Path | None = None) -> set[str]:
    """Load instance IDs to skip from a YAML file."""
    if path is None:
        default = _configs_dir() / "docker_skip.yaml"
        if default.exists():
            path = default
        else:
            return set()
    data = yaml.safe_load(path.read_text())
    ids = set(data.get("skip_instance_ids", []))
    if ids:
        logger.info("Loaded skip list: %d instance IDs from %s", len(ids), path.name)
    return ids


def load_instance_order(path: Path | None = None) -> list[str] | None:
    """Load a frozen, shuffled ordering of instance IDs. Returns None if no file."""
    if path is None:
        default = _configs_dir() / "instance_order.yaml"
        if not default.exists():
            return None
        path = default
    data = yaml.safe_load(path.read_text())
    ordered = data.get("ordered_instance_ids", [])
    logger.info("Loaded instance order: %d IDs from %s", len(ordered), path.name)
    return ordered


def load_instances(
    dataset_name: str = "SWE-bench/SWE-bench_Verified",
    split: str = "test",
    limit: int | None = None,
    skip_ids: set[str] | None = None,
    shuffle_seed: int | None = 42,
    order_file: Path | None = None,
    priority_ids: list[str] | None = None,
) -> list[SWEBenchInstance]:
    """Load SWE-bench instances.

    Order resolution:
      1. If `priority_ids` is given: keep ONLY those IDs, in the given order.
         Used by the prebuild workflow to run the pipeline against prebuilt images.
         Skip list is still honored.
      2. Else if `instance_order.yaml` (or `order_file`) exists: use that exact ordering,
         filter by current skip list. Adding to the skip list only removes items;
         the surviving prefix is identical to the prior run.
      3. Else: shuffle ALL instances with `shuffle_seed`, then filter by skip list.
         This still gives stable ordering across skip-list edits (new entries just
         drop out of the stream).
    """
    if skip_ids is None:
        skip_ids = load_skip_list()

    ds = load_dataset(dataset_name, split=split)
    all_rows = {row["instance_id"]: row for row in ds}

    if priority_ids:
        ordering = [iid for iid in priority_ids if iid in all_rows]
        order_label = f"priority={len(ordering)}"
    else:
        ordered_ids = load_instance_order(order_file)
        if ordered_ids is not None:
            ordering = [iid for iid in ordered_ids if iid in all_rows]
            order_label = "frozen"
        else:
            ordering = list(all_rows.keys())
            if shuffle_seed is not None:
                random.Random(shuffle_seed).shuffle(ordering)
            order_label = f"seed={shuffle_seed}"

    instances: list[SWEBenchInstance] = []
    skipped = 0
    for iid in ordering:
        if iid in skip_ids:
            skipped += 1
            continue
        row = all_rows[iid]
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

    if limit:
        instances = instances[:limit]

    logger.info("Loaded %d instances from %s (skipped %d, order=%s)",
                len(instances), dataset_name, skipped, order_label)
    return instances


def clone_repo(
    instance: SWEBenchInstance,
    work_dir: Path,
    shallow: bool = True,
) -> Path:
    """Clone the repo at base_commit into work_dir/{instance_id}/.

    `shallow=True` uses `--filter=blob:none` (partial clone): fetches the full commit
    graph but defers blob downloads until checkout. Typical 5-10x faster for large
    repos (Django, sklearn) with no observable downside for SWE-bench's use.
    """
    repo_dir = work_dir / instance.instance_id.replace("/", "__")
    if repo_dir.exists():
        logger.debug("Repo already cloned at %s", repo_dir)
        return repo_dir

    repo_url = f"https://github.com/{instance.repo}.git"
    logger.debug("Cloning %s at %s (shallow=%s)", repo_url, instance.base_commit, shallow)

    clone_cmd = ["git", "clone", "--quiet"]
    if shallow:
        clone_cmd += ["--filter=blob:none"]
    clone_cmd += [repo_url, str(repo_dir)]

    subprocess.run(clone_cmd, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "checkout", "--quiet", instance.base_commit],
        cwd=repo_dir, check=True, capture_output=True, text=True,
    )
    logger.debug("Cloned %s -> %s", instance.repo, repo_dir)
    return repo_dir
