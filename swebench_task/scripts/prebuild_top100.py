"""Prebuild Docker eval images for exactly the top-100 instances that don't have one yet.

Simpler than the generic `prebuild_images.py` which selects by (repo, version) buckets
across the full dataset. This script just diffs the top-100 list against `docker images`
and builds the missing ones.

Usage:
    uv run python -m swebench_task.scripts.prebuild_top100 --dry-run
    uv run python -m swebench_task.scripts.prebuild_top100 --workers 2 --yes
"""
import argparse
import logging
import subprocess
import sys
from pathlib import Path

import yaml

from swebench_task.utils.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _existing_eval_ids() -> set[str]:
    """Instance IDs that already have a `sweb.eval.*` Docker image."""
    result = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}"],
        capture_output=True, text=True, check=True,
    )
    ids = set()
    for line in result.stdout.strip().splitlines():
        if "sweb.eval" in line:
            ids.add(line.split("sweb.eval.x86_64.")[-1])
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workers", type=int, default=2, help="parallel docker builds")
    parser.add_argument("--dry-run", action="store_true", help="print plan only")
    parser.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    parser.add_argument("--dataset", default="SWE-bench/SWE-bench_Verified")
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=100, help="how many from the top of instance_order")
    args = parser.parse_args()

    configure_logging(Path("logs"), "prebuild_top100")

    order = yaml.safe_load(open("swebench_task/configs/instance_order.yaml"))
    top_n = order["ordered_instance_ids"][: args.limit]
    existing = _existing_eval_ids()
    need = [iid for iid in top_n if iid not in existing]

    print(f"Top-{args.limit}: {len(top_n) - len(need)} already built, {len(need)} need building")
    if not need:
        print("Nothing to do.")
        return 0

    est_gb = len(need) * 1.3
    print(f"Estimated additional disk: ~{est_gb:.0f} GB ({len(need)} × ~1.3 GB unique)")
    print()
    for iid in need:
        print(f"  {iid}")

    if args.dry_run:
        print("\n(dry run) — no docker calls.")
        return 0

    if not args.yes:
        resp = input(f"\nProceed to build {len(need)} images? [y/N] ").strip().lower()
        if resp not in {"y", "yes"}:
            print("Aborted.")
            return 1

    from swebench.harness.prepare_images import main as prepare_main

    logger.info("Building %d instance images (workers=%d)...", len(need), args.workers)
    prepare_main(
        dataset_name=args.dataset,
        split=args.split,
        instance_ids=need,
        max_workers=args.workers,
        force_rebuild=False,
        open_file_limit=8192,
        namespace=None,
        tag="latest",
        env_image_tag="latest",
    )

    after = _existing_eval_ids()
    built = set(need) & after
    failed = set(need) - after
    print(f"\nDone: {len(built)} built, {len(failed)} failed")
    if failed:
        print("Failed:")
        for iid in sorted(failed):
            print(f"  {iid}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
