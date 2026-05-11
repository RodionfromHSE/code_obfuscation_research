"""Heuristic audit: classify SWE-bench Verified instances by expected env-build RAM.

Reads MAP_REPO_VERSION_TO_SPECS_PY from the installed swebench package to compute
a score per (repo, version). Docker Desktop allocations of ~8GB and default
max_workers=4 mean each concurrent env build gets ~2GB — not enough for specs that
solve + link numpy/scipy/matplotlib/cython under conda or pip.

Usage:
    uv run python -m swebench_task.evaluation.oom_audit
    # writes swebench_task/docs/reports/oom_audit.md and prints the oom_likely list
"""
import argparse
import logging
import shutil
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml
from datasets import load_dataset

from swebench_task.utils.logging_config import configure_logging

logger = logging.getLogger(__name__)

HEAVY_CONDA_PKGS = {
    "numpy", "scipy", "pandas", "matplotlib", "cython",
    "scikit-learn", "astropy", "pytables", "h5py", "tensorflow",
    "torch", "pytorch", "pyqt", "pyqt5", "vtk",
}

HEAVY_PIP_PATTERNS = (
    "numpy", "scipy", "pandas", "matplotlib", "cython",
    "scikit-learn", "astropy", "torch", "tensorflow", "pyqt",
    "vtk", "h5py",
)


@dataclass(frozen=True, slots=True)
class OomScore:
    repo: str
    version: str
    python: str
    n_conda_heavy: int
    n_pip_heavy: int
    uses_requirements_txt: bool
    uses_environment_yml: bool
    has_editable_install: bool
    has_cython_build: bool
    score: int

    @property
    def classification(self) -> str:
        if self.score >= 6:
            return "oom_likely"
        if self.score >= 3:
            return "risky"
        return "safe"


def _score_spec(repo: str, version: str, spec: dict) -> OomScore:
    python = spec.get("python", "?")
    packages = spec.get("packages", "")
    pip_packages = spec.get("pip_packages", []) or []
    install = spec.get("install", "")

    uses_req = packages == "requirements.txt"
    uses_yml = packages == "environment.yml"

    if packages and not uses_req and not uses_yml:
        conda_pkgs = packages.split()
    else:
        conda_pkgs = []

    n_conda_heavy = sum(1 for p in conda_pkgs if p.lower() in HEAVY_CONDA_PKGS)
    n_pip_heavy = sum(
        1 for p in pip_packages
        if any(pat in str(p).lower() for pat in HEAVY_PIP_PATTERNS)
    )

    has_editable = "-e ." in install
    has_cython = "cython" in (packages + " " + " ".join(map(str, pip_packages))).lower()

    score = (
        3 * n_conda_heavy
        + 2 * n_pip_heavy
        + (2 if has_cython and has_editable else 0)
        + (3 if uses_req else 0)
        + (2 if uses_yml else 0)
        + (1 if python.startswith("3.5") or python.startswith("3.6") else 0)
    )

    return OomScore(
        repo=repo,
        version=version,
        python=python,
        n_conda_heavy=n_conda_heavy,
        n_pip_heavy=n_pip_heavy,
        uses_requirements_txt=uses_req,
        uses_environment_yml=uses_yml,
        has_editable_install=has_editable,
        has_cython_build=has_cython,
        score=score,
    )


def _docker_memory_gb() -> float | None:
    if shutil.which("docker") is None:
        return None
    try:
        out = subprocess.run(
            ["docker", "info", "--format", "{{.MemTotal}}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return int(out) / (1024**3)
    except Exception:
        return None


def run_audit(
    dataset_name: str,
    split: str,
    existing_skip: set[str],
    output_md: Path,
    output_skip_additions: Path,
) -> None:
    from swebench.harness.constants.python import MAP_REPO_VERSION_TO_SPECS_PY

    ds = load_dataset(dataset_name, split=split)
    rows = list(ds)

    by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        by_key[(row["repo"], row["version"])].append(row["instance_id"])

    scores: list[OomScore] = []
    unscorable: list[tuple[str, str, list[str]]] = []
    for (repo, version), ids in sorted(by_key.items()):
        spec = MAP_REPO_VERSION_TO_SPECS_PY.get(repo, {}).get(version)
        if spec is None:
            unscorable.append((repo, version, ids))
            continue
        scores.append(_score_spec(repo, version, spec))

    by_class: dict[str, list[OomScore]] = defaultdict(list)
    for s in scores:
        by_class[s.classification].append(s)

    instances_by_class: dict[str, list[str]] = defaultdict(list)
    for s in scores:
        for iid in by_key[(s.repo, s.version)]:
            if iid in existing_skip:
                continue
            instances_by_class[s.classification].append(iid)

    docker_mem = _docker_memory_gb()

    lines = _render_report(
        dataset_name=dataset_name,
        total_instances=len(rows),
        existing_skip_count=len(existing_skip),
        docker_mem_gb=docker_mem,
        scores=scores,
        by_class=by_class,
        instances_by_class=instances_by_class,
        unscorable=unscorable,
    )
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines))
    logger.info("Wrote OOM audit report -> %s", output_md)

    additions = sorted(instances_by_class["oom_likely"])
    output_skip_additions.parent.mkdir(parents=True, exist_ok=True)
    output_skip_additions.write_text(yaml.safe_dump(
        {"oom_likely_additions": additions}, sort_keys=False,
    ))
    logger.info("Wrote %d oom_likely additions -> %s", len(additions), output_skip_additions)
    print(f"\nOOM-likely additions: {len(additions)} instances")
    print(f"  Risky (warn only): {len(instances_by_class['risky'])} instances")
    print(f"  Safe: {len(instances_by_class['safe'])} instances")


def _render_report(
    dataset_name: str,
    total_instances: int,
    existing_skip_count: int,
    docker_mem_gb: float | None,
    scores: list[OomScore],
    by_class: dict[str, list[OomScore]],
    instances_by_class: dict[str, list[str]],
    unscorable: list[tuple[str, str, list[str]]],
) -> list[str]:
    lines: list[str] = []
    lines.append("# Docker OOM audit: SWE-bench Verified")
    lines.append("")
    lines.append("Heuristic score per `(repo, version)` env image based on `MAP_REPO_VERSION_TO_SPECS_PY`.")
    lines.append("Goal: identify env images likely to OOM under Docker Desktop memory limits.")
    lines.append("")
    lines.append("## Host / Docker")
    lines.append("")
    lines.append(f"- Dataset: `{dataset_name}` ({total_instances} instances)")
    lines.append(f"- Already skipped: {existing_skip_count}")
    if docker_mem_gb is not None:
        lines.append(
            f"- Docker Desktop memory: **{docker_mem_gb:.1f} GB** "
            "(from `docker info --format '{{{{.MemTotal}}}}'`)"
        )
    else:
        lines.append("- Docker Desktop memory: unknown (docker not reachable)")
    per_build = (docker_mem_gb or 8) / 4
    lines.append(
        f"- Default `max_workers=4` for env builds -> each concurrent build sees ~{per_build:.1f} GB peak"
    )
    lines.append("")
    lines.append("## Scoring")
    lines.append("")
    lines.append("Per spec (higher = riskier):")
    lines.append("")
    lines.append("| Factor | Weight |")
    lines.append("|---|---|")
    lines.append("| heavy conda package (numpy/scipy/matplotlib/cython/pandas/sklearn/astropy/...) | 3 each |")
    lines.append("| heavy pip package | 2 each |")
    lines.append("| `cython` + `-e .` editable install (compiles extensions) | 2 |")
    lines.append("| `packages == requirements.txt` (opaque — must solve full graph) | 3 |")
    lines.append("| `packages == environment.yml` | 2 |")
    lines.append("| python 3.5 or 3.6 (old wheels, more compiles) | 1 |")
    lines.append("")
    lines.append("Classification: score >= 6 -> `oom_likely`; 3..5 -> `risky`; < 3 -> `safe`.")
    lines.append("")
    lines.append("## Summary by class")
    lines.append("")
    lines.append("| Class | # env specs | # instances (post-skip) |")
    lines.append("|---|---|---|")
    for cls in ["oom_likely", "risky", "safe"]:
        n_specs = len(by_class.get(cls, []))
        n_insts = len(instances_by_class.get(cls, []))
        lines.append(f"| `{cls}` | {n_specs} | {n_insts} |")
    lines.append("")

    lines.append("## Per-repo class distribution")
    lines.append("")
    lines.append("| Repo | oom_likely | risky | safe |")
    lines.append("|---|---|---|---|")
    by_repo: dict[str, Counter] = defaultdict(Counter)
    for s in scores:
        by_repo[s.repo][s.classification] += 1
    for repo in sorted(by_repo):
        c = by_repo[repo]
        lines.append(f"| `{repo}` | {c.get('oom_likely', 0)} | {c.get('risky', 0)} | {c.get('safe', 0)} |")
    lines.append("")

    lines.append("## OOM-likely env specs")
    lines.append("")
    lines.append("| Repo | Version | Python | Conda pkgs (heavy) | Pip pkgs (heavy) | Flags | Score |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in sorted(by_class.get("oom_likely", []), key=lambda x: (-x.score, x.repo, x.version)):
        flags = []
        if s.uses_requirements_txt:
            flags.append("req.txt")
        if s.uses_environment_yml:
            flags.append("env.yml")
        if s.has_cython_build:
            flags.append("cython")
        if s.has_editable_install:
            flags.append("ed")
        flags_s = ", ".join(flags)
        lines.append(
            f"| `{s.repo}` | {s.version} | {s.python} | {s.n_conda_heavy} | "
            f"{s.n_pip_heavy} | {flags_s} | {s.score} |"
        )
    lines.append("")

    lines.append("## Risky env specs (not auto-skipped; tune max_workers)")
    lines.append("")
    lines.append("| Repo | Version | Score |")
    lines.append("|---|---|---|")
    for s in sorted(by_class.get("risky", []), key=lambda x: (-x.score, x.repo, x.version)):
        lines.append(f"| `{s.repo}` | {s.version} | {s.score} |")
    lines.append("")

    if unscorable:
        lines.append("## Unscorable (no spec found)")
        lines.append("")
        for repo, version, ids in unscorable:
            lines.append(f"- `{repo}` @ `{version}` ({len(ids)} instances)")
        lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    if docker_mem_gb is not None and docker_mem_gb < 12:
        lines.append(f"1. **Bump Docker Desktop memory from {docker_mem_gb:.1f} GB to >= 16 GB.** "
                     "Single biggest lever. The 4 heavy-env parallel build scenario currently "
                     f"allocates ~{docker_mem_gb/4:.1f} GB per build — below the ~3 GB needed for "
                     "conda solves with numpy/scipy/matplotlib.")
    lines.append("2. Lower `eval.max_workers` from 4 to 2 when running heavy repos (sklearn, astropy, "
                 "matplotlib). Halves peak memory.")
    lines.append("3. Skip the `oom_likely` list above — append to `docker_skip.yaml`.")
    lines.append("4. Pre-build env images with `cache_level=env` (already on). First run builds "
                 "once, subsequent runs are free.")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="SWE-bench/SWE-bench_Verified")
    parser.add_argument("--split", default="test")
    parser.add_argument(
        "--output-md", type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "reports" / "oom_audit.md",
    )
    parser.add_argument(
        "--output-skip", type=Path,
        default=Path(__file__).resolve().parents[1] / "configs" / "oom_audit_additions.yaml",
    )
    args = parser.parse_args()

    configure_logging(Path("logs"), "oom_audit")

    from swebench_task.source.dataset import load_skip_list
    existing = load_skip_list()

    run_audit(
        dataset_name=args.dataset,
        split=args.split,
        existing_skip=existing,
        output_md=args.output_md,
        output_skip_additions=args.output_skip,
    )


if __name__ == "__main__":
    main()
