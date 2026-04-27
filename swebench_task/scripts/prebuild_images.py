"""Prebuild SWE-bench docker images for the top-K most populous (repo, version) buckets.

Out-of-band from the pipeline: run this once, then pipeline evals become fast because
the `sweb.eval.*` instance images already exist. Pipeline's `cache_level='env'` +
`clean=False` semantics keep prebuilt images across runs and auto-clean ad-hoc ones.

Usage:
    uv run python -m swebench_task.scripts.prebuild_images --top-k 3 --max-total-gb 40
    uv run python -m swebench_task.scripts.prebuild_images --dry-run
"""
import argparse
import logging
import sys
from pathlib import Path

from swebench_task.prebuild.image_selection import (
    format_plan_table,
    group_by_repo_version,
    select_top_k_buckets,
)
from swebench_task.prebuild.prebuilder import run_prebuild
from swebench_task.prebuild.priority_yaml import write_priority_yaml
from swebench_task.source.dataset import load_instances
from swebench_task.utils.logging_config import configure_logging

logger = logging.getLogger(__name__)

DEFAULT_ML4SE_DIR = Path.home() / "Downloads" / "ml4se_images"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--top-k", type=int, default=3,
                        help="max number of (repo, version) buckets to prebuild")
    parser.add_argument("--max-total-gb", type=float, default=40.0,
                        help="disk budget in GB (hard cap, includes env + instance images)")
    parser.add_argument("--workers", type=int, default=4,
                        help="parallel docker builds (watch memory pressure)")
    parser.add_argument("--ml4se-dir", type=Path, default=DEFAULT_ML4SE_DIR,
                        help="where to drop manifest.json + cleanup.sh + disk_report.txt")
    parser.add_argument("--dataset", default="SWE-bench/SWE-bench_Verified")
    parser.add_argument("--split", default="test")
    parser.add_argument("--force-rebuild", action="store_true",
                        help="rebuild images even if they already exist on disk")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan; don't call docker or write manifest")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="skip confirmation prompt")
    parser.add_argument("--repo", default=None,
                        help="restrict to buckets whose repo contains this substring "
                             "(e.g. 'pytest' for smoke tests)")
    args = parser.parse_args()

    configure_logging(Path("logs"), "prebuild_images")

    logger.info(
        "Loading %s / %s (full dataset for grouping; skip list still applies)",
        args.dataset, args.split,
    )
    instances = load_instances(
        dataset_name=args.dataset, split=args.split, limit=None, shuffle_seed=None,
    )
    buckets = group_by_repo_version(instances)
    if args.repo:
        buckets = [b for b in buckets if args.repo.lower() in b.repo.lower()]
        logger.info("Repo filter '%s' -> %d buckets remain", args.repo, len(buckets))
    plan = select_top_k_buckets(
        buckets=buckets,
        top_k=args.top_k,
        max_total_gb=args.max_total_gb,
    )

    print(format_plan_table(plan))
    print()

    if not plan.instance_ids:
        print("No buckets selected. Nothing to do.")
        return 1

    yaml_path = write_priority_yaml(plan)
    print(f"Wrote priority list -> {yaml_path}")

    if args.dry_run:
        print("(dry run) skipping docker calls and manifest writing.")
        return 0

    if not args.yes:
        resp = input(
            f"Proceed to build {len(plan.instance_ids)} images "
            f"(~{plan.estimated_gb:.1f} GB) into docker? [y/N] "
        ).strip().lower()
        if resp not in {"y", "yes"}:
            print("Aborted.")
            return 1

    manifest = run_prebuild(
        plan=plan,
        dataset_name=args.dataset,
        split=args.split,
        ml4se_dir=args.ml4se_dir,
        max_workers=args.workers,
        force_rebuild=args.force_rebuild,
    )
    print(
        f"\nPrebuild complete: {len(manifest.instance_images)} instance images "
        f"({manifest.total_size_gb:.1f} GB actual) -> {args.ml4se_dir}"
    )
    print(f"Cleanup later:  bash {args.ml4se_dir}/cleanup.sh")
    try:
        rel = yaml_path.relative_to(Path.cwd())
    except ValueError:
        rel = yaml_path
    print(f"Run pipeline:  uv run python -m swebench_task priority_instances={rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
