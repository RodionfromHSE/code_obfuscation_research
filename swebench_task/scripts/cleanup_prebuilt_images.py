"""Remove docker images listed in a prebuild manifest. Updates manifest with post-state.

Usage:
    uv run python -m swebench_task.scripts.cleanup_prebuilt_images
    uv run python -m swebench_task.scripts.cleanup_prebuilt_images --ml4se-dir ~/Downloads/ml4se_images --dry-run
"""
import argparse
import logging
import subprocess
import sys
from pathlib import Path

from swebench_task.prebuild.manifest import PrebuildManifest, write_disk_report
from swebench_task.prebuild.prebuilder import docker_disk_report, list_sweb_images
from swebench_task.scripts.prebuild_images import DEFAULT_ML4SE_DIR
from swebench_task.utils.logging_config import configure_logging

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ml4se-dir", type=Path, default=DEFAULT_ML4SE_DIR,
                        help="directory containing manifest.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="list images that would be removed; make no changes")
    parser.add_argument("--keep-files", action="store_true",
                        help="don't delete manifest.json / cleanup.sh after successful rmi")
    args = parser.parse_args()

    configure_logging(Path("logs"), "cleanup_prebuilt_images")

    ml4se_dir = args.ml4se_dir.expanduser().resolve()
    if not (ml4se_dir / "manifest.json").exists():
        print(f"No manifest found at {ml4se_dir}/manifest.json", file=sys.stderr)
        return 1

    manifest = PrebuildManifest.read(ml4se_dir)
    tags = manifest.all_image_tags
    if not tags:
        print("Manifest lists no images. Nothing to remove.")
        return 0

    existing = {img.tag for img in list_sweb_images()}
    to_remove = [t for t in tags if t in existing]
    missing = [t for t in tags if t not in existing]
    if missing:
        logger.info("%d image(s) listed in manifest are already gone", len(missing))

    print(f"Will remove {len(to_remove)} docker images:")
    for t in to_remove:
        print(f"  - {t}")
    if args.dry_run:
        print("(dry run) no changes.")
        return 0

    write_disk_report(
        "=== docker system df BEFORE cleanup ===\n" + docker_disk_report(),
        ml4se_dir,
    )

    result = subprocess.run(
        ["docker", "rmi", "-f", *to_remove],
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)

    write_disk_report(
        "=== docker system df AFTER cleanup ===\n" + docker_disk_report(),
        ml4se_dir,
    )

    if not args.keep_files:
        for name in ("manifest.json", "cleanup.sh"):
            p = ml4se_dir / name
            if p.exists():
                p.unlink()
        print(f"Removed manifest + cleanup.sh from {ml4se_dir}. disk_report.txt kept for reference.")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
