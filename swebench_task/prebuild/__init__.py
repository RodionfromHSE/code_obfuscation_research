"""Prebuild top-K SWE-bench Docker images out-of-band from the pipeline.

See swebench_task/docs/guides/prebuild_images.md for usage.
"""
from swebench_task.prebuild.image_selection import (
    Bucket,
    PrebuildPlan,
    estimate_bucket_gb,
    group_by_repo_version,
    select_top_k_buckets,
)
from swebench_task.prebuild.manifest import (
    BucketEntry,
    InstanceImageEntry,
    PrebuildManifest,
)

__all__ = [
    "Bucket",
    "BucketEntry",
    "InstanceImageEntry",
    "PrebuildManifest",
    "PrebuildPlan",
    "estimate_bucket_gb",
    "group_by_repo_version",
    "select_top_k_buckets",
]
