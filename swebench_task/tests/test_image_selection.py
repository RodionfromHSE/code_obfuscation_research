"""Unit tests for bucket grouping + top-K-under-budget selection. No docker, no HF."""
from dataclasses import dataclass

from swebench_task.prebuild.image_selection import (
    DEFAULT_ENV_IMAGE_GB,
    DEFAULT_INSTANCE_IMAGE_GB,
    Bucket,
    estimate_bucket_gb,
    format_plan_table,
    group_by_repo_version,
    select_top_k_buckets,
)


@dataclass(frozen=True, slots=True)
class _Inst:
    instance_id: str
    repo: str
    version: str


def _make_instances(spec: dict[tuple[str, str], int]) -> list[_Inst]:
    """Build synthetic instances: {(repo, version): n} -> flat list with unique ids."""
    out = []
    for (repo, version), n in spec.items():
        for i in range(n):
            out.append(_Inst(
                instance_id=f"{repo.replace('/', '__')}-{version}-{i:03d}",
                repo=repo, version=version,
            ))
    return out


def test_grouping_sorts_by_size_desc_then_name():
    instances = _make_instances({
        ("django/django", "5.0"): 3,
        ("sympy/sympy", "1.12"): 5,
        ("pallets/flask", "2.0"): 5,  # tie with sympy on size
    })
    buckets = group_by_repo_version(instances)
    assert [b.size for b in buckets] == [5, 5, 3]
    # tie-break alphabetical on repo
    assert buckets[0].repo == "pallets/flask"
    assert buckets[1].repo == "sympy/sympy"


def test_grouping_instance_ids_are_sorted_and_tuple():
    instances = _make_instances({("r/x", "1"): 3})
    [bucket] = group_by_repo_version(instances)
    assert isinstance(bucket.instance_ids, tuple)
    assert list(bucket.instance_ids) == sorted(bucket.instance_ids)


def test_estimate_uses_repo_lookup_then_default():
    b = Bucket(repo="django/django", version="5.0", instance_ids=("a", "b"))
    est = estimate_bucket_gb(b)
    assert est == 2 * DEFAULT_INSTANCE_IMAGE_GB + 4.0

    unknown = Bucket(repo="unknown/repo", version="9", instance_ids=("a",))
    est_unknown = estimate_bucket_gb(unknown)
    assert est_unknown == DEFAULT_INSTANCE_IMAGE_GB + DEFAULT_ENV_IMAGE_GB


def test_select_top_k_caps_by_count():
    buckets = group_by_repo_version(_make_instances({
        ("a/a", "1"): 10,
        ("b/b", "1"): 5,
        ("c/c", "1"): 3,
    }))
    plan = select_top_k_buckets(buckets, top_k=2, max_total_gb=9999)
    assert len(plan.buckets) == 2
    assert plan.buckets[0].size == 10
    assert plan.buckets[1].size == 5
    assert len(plan.skipped_buckets) == 1
    assert plan.skipped_buckets[0].size == 3
    assert len(plan.instance_ids) == 15


def test_select_top_k_caps_by_budget():
    # each bucket ~5 GB env + 1.2 GB/instance. 3 instances => ~8.6 GB.
    buckets = group_by_repo_version(_make_instances({
        ("a/a", "1"): 3,
        ("b/b", "1"): 3,
        ("c/c", "1"): 3,
    }))
    plan = select_top_k_buckets(buckets, top_k=10, max_total_gb=10)
    assert len(plan.buckets) == 1
    assert not plan.budget_exceeded
    assert len(plan.skipped_buckets) == 2


def test_select_takes_oversized_first_bucket_with_flag():
    buckets = group_by_repo_version(_make_instances({
        ("a/a", "1"): 100,  # way over any tiny budget
    }))
    plan = select_top_k_buckets(buckets, top_k=3, max_total_gb=2)
    assert len(plan.buckets) == 1
    assert plan.budget_exceeded is True
    assert plan.estimated_gb > plan.budget_gb


def test_select_ordering_is_deterministic():
    instances = _make_instances({
        ("a/a", "1"): 5,
        ("b/b", "1"): 5,
        ("c/c", "1"): 5,
    })
    buckets = group_by_repo_version(instances)
    plan_a = select_top_k_buckets(buckets, top_k=2, max_total_gb=9999)
    plan_b = select_top_k_buckets(buckets, top_k=2, max_total_gb=9999)
    assert plan_a.instance_ids == plan_b.instance_ids


def test_empty_dataset_returns_empty_plan():
    plan = select_top_k_buckets([], top_k=3, max_total_gb=50)
    assert plan.instance_ids == ()
    assert plan.buckets == ()
    assert plan.estimated_gb == 0.0


def test_format_plan_table_includes_key_fields():
    buckets = group_by_repo_version(_make_instances({("a/a", "1"): 2}))
    plan = select_top_k_buckets(buckets, top_k=1, max_total_gb=50)
    out = format_plan_table(plan)
    assert "a/a" in out
    assert "top_k=1" in out
    assert "2" in out  # n_inst
