"""Unit tests for PrebuildManifest JSON round-trip + cleanup.sh generation."""
import json
from pathlib import Path

from swebench_task.prebuild.manifest import (
    CLEANUP_SCRIPT_FILENAME,
    MANIFEST_FILENAME,
    BucketEntry,
    InstanceImageEntry,
    PrebuildManifest,
    generate_cleanup_script,
    shell_quote,
    write_cleanup_script,
)


def _sample_manifest(ml4se_dir: Path) -> PrebuildManifest:
    m = PrebuildManifest.new(
        dataset="SWE-bench/SWE-bench_Verified",
        top_k=2,
        max_total_gb=20.0,
        ml4se_dir=ml4se_dir,
    )
    m.buckets.append(BucketEntry(
        repo="django/django", version="5.0", n_instances=2,
        env_image="sweb.env.x86_64.django__django_5-0:latest",
    ))
    m.instance_images.extend([
        InstanceImageEntry(tag="sweb.eval.x86_64.django__django-15000:latest",
                           instance_id="django__django-15000", size_bytes=1_200_000_000),
        InstanceImageEntry(tag="sweb.eval.x86_64.django__django-15001:latest",
                           instance_id="django__django-15001", size_bytes=1_300_000_000),
    ])
    m.total_size_bytes = sum(e.size_bytes for e in m.instance_images)
    return m


def test_manifest_round_trip(tmp_path: Path):
    m = _sample_manifest(tmp_path)
    m.write(tmp_path)

    loaded = PrebuildManifest.read(tmp_path)
    assert loaded.dataset == m.dataset
    assert loaded.top_k == m.top_k
    assert len(loaded.buckets) == 1
    assert loaded.buckets[0].env_image == "sweb.env.x86_64.django__django_5-0:latest"
    assert len(loaded.instance_images) == 2
    assert loaded.total_size_bytes == m.total_size_bytes


def test_manifest_json_is_valid_on_disk(tmp_path: Path):
    m = _sample_manifest(tmp_path)
    path = m.write(tmp_path)
    assert path == tmp_path / MANIFEST_FILENAME
    data = json.loads(path.read_text())
    assert data["buckets"][0]["repo"] == "django/django"
    assert "total_size_gb" in data


def test_cleanup_script_contains_every_tag(tmp_path: Path):
    m = _sample_manifest(tmp_path)
    script = generate_cleanup_script(m)
    for entry in m.instance_images:
        assert entry.tag in script
    for bucket in m.buckets:
        assert bucket.env_image in script
    assert "docker rmi -f" in script


def test_cleanup_script_handles_empty_manifest():
    empty = PrebuildManifest.new(
        dataset="x", top_k=0, max_total_gb=0, ml4se_dir=Path("/tmp/nowhere"),
    )
    script = generate_cleanup_script(empty)
    assert "Nothing to remove" in script


def test_write_cleanup_script_is_executable(tmp_path: Path):
    m = _sample_manifest(tmp_path)
    path = write_cleanup_script(m, tmp_path)
    assert path == tmp_path / CLEANUP_SCRIPT_FILENAME
    assert path.stat().st_mode & 0o111  # executable bit set


def test_shell_quote_preserves_tags_with_colons_and_dots():
    assert shell_quote("sweb.eval.x86_64.abc:latest") == "'sweb.eval.x86_64.abc:latest'"


def test_all_image_tags_includes_env_and_instance(tmp_path: Path):
    m = _sample_manifest(tmp_path)
    tags = m.all_image_tags
    assert "sweb.eval.x86_64.django__django-15000:latest" in tags
    assert "sweb.env.x86_64.django__django_5-0:latest" in tags
