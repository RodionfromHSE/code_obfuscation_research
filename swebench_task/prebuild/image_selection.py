"""Pure bucket-selection logic: group instances by (repo, version), pick top-K under disk budget.

No docker, no HF dataset; accepts any iterable of objects exposing `instance_id`, `repo`,
`version`. Makes it trivial to unit-test without network.
"""
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

DEFAULT_INSTANCE_IMAGE_GB: float = 1.2  # typical sweb.eval.* image on top of env
DEFAULT_ENV_IMAGE_GB: float = 5.0       # amortized sweb.env.* image

# rough env image sizes by repo (GB). fall back to DEFAULT_ENV_IMAGE_GB.
REPO_ENV_SIZE_GB: dict[str, float] = {
    "django/django": 4.0,
    "sympy/sympy": 3.0,
    "matplotlib/matplotlib": 7.0,
    "pytest-dev/pytest": 2.5,
    "psf/requests": 2.0,
    "sphinx-doc/sphinx": 3.0,
    "pylint-dev/pylint": 2.5,
    "pallets/flask": 2.0,
    "scikit-learn/scikit-learn": 8.0,
    "astropy/astropy": 8.0,
    "pydata/xarray": 6.0,
    "mwaskom/seaborn": 5.0,
}


@runtime_checkable
class _InstanceLike(Protocol):
    instance_id: str
    repo: str
    version: str


@dataclass(frozen=True, slots=True)
class Bucket:
    repo: str
    version: str
    instance_ids: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.instance_ids)


@dataclass(frozen=True, slots=True)
class PrebuildPlan:
    buckets: tuple[Bucket, ...]
    instance_ids: tuple[str, ...]
    estimated_gb: float
    budget_gb: float
    top_k: int
    budget_exceeded: bool = False
    skipped_buckets: tuple[Bucket, ...] = field(default_factory=tuple)


def estimate_bucket_gb(
    bucket: Bucket,
    instance_gb: float = DEFAULT_INSTANCE_IMAGE_GB,
    env_gb_map: dict[str, float] | None = None,
) -> float:
    """Rough GB estimate: (n_instances * instance_gb) + env_image_gb."""
    env_map = env_gb_map if env_gb_map is not None else REPO_ENV_SIZE_GB
    env_gb = env_map.get(bucket.repo, DEFAULT_ENV_IMAGE_GB)
    return bucket.size * instance_gb + env_gb


def group_by_repo_version(instances: Iterable[_InstanceLike]) -> list[Bucket]:
    """Group instances by (repo, version). Returns buckets sorted by size desc, then name."""
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for inst in instances:
        grouped[(inst.repo, inst.version)].append(inst.instance_id)

    buckets = [
        Bucket(repo=repo, version=ver, instance_ids=tuple(sorted(ids)))
        for (repo, ver), ids in grouped.items()
    ]
    buckets.sort(key=lambda b: (-b.size, b.repo, b.version))
    return buckets


def select_top_k_buckets(
    buckets: list[Bucket],
    top_k: int,
    max_total_gb: float,
    instance_gb: float = DEFAULT_INSTANCE_IMAGE_GB,
    env_gb_map: dict[str, float] | None = None,
) -> PrebuildPlan:
    """Greedy selection of top buckets under a disk-budget cap.

    Tie-break: buckets are assumed pre-sorted by size desc; caller uses
    `group_by_repo_version` which also breaks ties by (repo, version).

    Edge case: if the single largest bucket already exceeds the budget, include
    it and flag `budget_exceeded=True` so the CLI can warn.
    """
    taken: list[Bucket] = []
    skipped: list[Bucket] = []
    total_gb = 0.0
    budget_exceeded = False

    for bucket in buckets:
        if len(taken) >= top_k:
            skipped.append(bucket)
            continue
        b_gb = estimate_bucket_gb(bucket, instance_gb=instance_gb, env_gb_map=env_gb_map)
        if not taken and b_gb > max_total_gb:
            # single bucket overflows budget; take it anyway, flag it
            taken.append(bucket)
            total_gb += b_gb
            budget_exceeded = True
            continue
        if total_gb + b_gb > max_total_gb:
            skipped.append(bucket)
            continue
        taken.append(bucket)
        total_gb += b_gb

    all_instance_ids = tuple(
        iid for b in taken for iid in b.instance_ids
    )
    return PrebuildPlan(
        buckets=tuple(taken),
        instance_ids=all_instance_ids,
        estimated_gb=round(total_gb, 2),
        budget_gb=max_total_gb,
        top_k=top_k,
        budget_exceeded=budget_exceeded,
        skipped_buckets=tuple(skipped),
    )


def format_plan_table(plan: PrebuildPlan) -> str:
    """Human-readable plan summary (printed by the CLI)."""
    lines = [
        f"Prebuild plan: top_k={plan.top_k}, budget={plan.budget_gb:.1f} GB, "
        f"estimated={plan.estimated_gb:.1f} GB, {len(plan.instance_ids)} instances",
    ]
    if plan.budget_exceeded:
        lines.append("! WARNING: single bucket exceeds budget; including anyway.")
    lines.append("")
    lines.append(f"{'repo':<32} {'version':<10} {'n_inst':>6}  est_gb")
    lines.append("-" * 64)
    for b in plan.buckets:
        est = estimate_bucket_gb(b)
        lines.append(f"{b.repo:<32} {b.version:<10} {b.size:>6}  {est:>5.1f}")
    if plan.skipped_buckets:
        lines.append("")
        lines.append(f"Skipped {len(plan.skipped_buckets)} buckets (over budget or beyond top_k).")
    return "\n".join(lines)
