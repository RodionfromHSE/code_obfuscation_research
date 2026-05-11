"""Wrap swebench.harness.prepare_images.main + pre/post image inventory -> manifest."""
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from swebench_task.prebuild.image_selection import PrebuildPlan
from swebench_task.prebuild.manifest import (
    BucketEntry,
    InstanceImageEntry,
    PrebuildManifest,
    write_cleanup_script,
    write_disk_report,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DockerImage:
    tag: str
    size_bytes: int


def list_sweb_images() -> list[DockerImage]:
    """List docker images matching sweb.* via the docker CLI (avoids python SDK dep here)."""
    out = subprocess.run(
        ["docker", "images", "--filter", "reference=sweb.*",
         "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not out:
        return []
    images = []
    for line in out.splitlines():
        tag, size_str = line.split("\t", 1)
        images.append(DockerImage(tag=tag, size_bytes=_parse_docker_size(size_str)))
    return images


def _parse_docker_size(s: str) -> int:
    """Parse `docker images` human size ('4.12GB', '950MB') to bytes. Returns 0 on failure."""
    s = s.strip()
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    for unit, mult in sorted(units.items(), key=lambda kv: -len(kv[0])):
        if s.upper().endswith(unit):
            try:
                return int(float(s[: -len(unit)].strip()) * mult)
            except ValueError:
                return 0
    return 0


def docker_disk_report() -> str:
    """Snapshot `docker system df` for the disk_report.txt file."""
    try:
        return subprocess.run(
            ["docker", "system", "df"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return f"(failed to capture docker system df: {e})\n"


def run_prebuild(
    plan: PrebuildPlan,
    dataset_name: str,
    split: str,
    ml4se_dir: Path,
    max_workers: int = 4,
    force_rebuild: bool = False,
) -> PrebuildManifest:
    """Invoke swebench.harness.prepare_images, then write manifest + cleanup.sh + disk report.

    This function expects Docker to be running.
    """
    from swebench.harness.prepare_images import main as prepare_main

    ml4se_dir = ml4se_dir.expanduser().resolve()
    ml4se_dir.mkdir(parents=True, exist_ok=True)

    before = {img.tag for img in list_sweb_images()}
    logger.info("Existing sweb.* images before prebuild: %d", len(before))

    write_disk_report(
        "=== docker system df BEFORE prebuild ===\n" + docker_disk_report(),
        ml4se_dir,
    )

    logger.info(
        "Prebuilding %d instance images across %d buckets (workers=%d)...",
        len(plan.instance_ids), len(plan.buckets), max_workers,
    )
    prepare_main(
        dataset_name=dataset_name,
        split=split,
        instance_ids=list(plan.instance_ids),
        max_workers=max_workers,
        force_rebuild=force_rebuild,
        open_file_limit=8192,
        namespace=None,
        tag="latest",
        env_image_tag="latest",
    )

    after_images = list_sweb_images()
    after = {img.tag: img for img in after_images}
    new_tags = set(after.keys()) - before
    logger.info("Newly built images: %d", len(new_tags))

    manifest = PrebuildManifest.new(
        dataset=dataset_name,
        top_k=plan.top_k,
        max_total_gb=plan.budget_gb,
        ml4se_dir=ml4se_dir,
        budget_exceeded=plan.budget_exceeded,
    )

    for bucket in plan.buckets:
        env_tag = _match_env_tag(bucket.repo, after.keys())
        manifest.buckets.append(BucketEntry(
            repo=bucket.repo,
            version=bucket.version,
            n_instances=bucket.size,
            env_image=env_tag,
        ))

    for iid in plan.instance_ids:
        tag = _instance_image_tag(iid, after.keys())
        size = after[tag].size_bytes if tag and tag in after else 0
        if tag is None:
            logger.warning("No image found for instance %s (build may have failed)", iid)
            continue
        manifest.instance_images.append(InstanceImageEntry(
            tag=tag, instance_id=iid, size_bytes=size,
        ))

    manifest.total_size_bytes = sum(e.size_bytes for e in manifest.instance_images)

    manifest.write(ml4se_dir)
    cleanup = write_cleanup_script(manifest, ml4se_dir)
    write_disk_report(
        "=== docker system df AFTER prebuild ===\n" + docker_disk_report(),
        ml4se_dir,
    )
    logger.info("Cleanup script -> %s", cleanup)
    return manifest


def _instance_image_tag(instance_id: str, existing: set[str] | list | dict) -> str | None:
    """Find the sweb.eval.* tag matching an instance_id among existing docker tags.

    SWE-bench names images `sweb.eval.{arch}.{instance_id.lower()}:{tag}`.
    """
    target = instance_id.lower()
    tags = list(existing)
    for tag in tags:
        if tag.startswith("sweb.eval.") and f".{target}:" in tag:
            return tag
    return None


def _match_env_tag(repo: str, existing: set[str] | list | dict) -> str | None:
    """Best-effort: find a sweb.env.* tag matching the repo (no version discrimination)."""
    repo_slug = repo.replace("/", "__").lower()
    tags = list(existing)
    for tag in tags:
        if tag.startswith("sweb.env.") and repo_slug.split("__")[-1] in tag.lower():
            return tag
    return None
