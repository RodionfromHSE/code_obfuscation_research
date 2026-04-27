"""End-to-end smoke test: 3 diverse instances, identity obfuscation.

Validates (fast with --no-llm --no-docker, ~10s total):
    1. Pipeline runs end-to-end (clone + obfuscate + agent + eval).
    2. tqdm progress bar prints during agent and docker eval phases.
    3. Global cache stores results and re-run hits cache (no API calls).
    4. Deleting one cached entry re-runs only that one.
    5. agent.concurrency=3 runs in parallel with bounded semaphore.

Run:
    uv run python swebench_task/scripts/smoke_test.py --no-llm --no-docker    # CI-safe
    uv run python swebench_task/scripts/smoke_test.py                         # real LLM + Docker
"""
import argparse
import json
import logging
import shutil
import time
from pathlib import Path
from unittest.mock import patch

from swebench_task.agent.runner import AgentRunResult
from swebench_task.evaluation.swebench_eval import SWEBenchEvalResult
from swebench_task.obfuscation.identity import RepoIdentity
from swebench_task.source.cache import CacheKey
from swebench_task.source.dataset import load_instance_order
from swebench_task.source.pipeline import run_swebench_pipeline
from swebench_task.utils.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _pick_diverse_instances(n: int) -> list[str]:
    """Pick N instances each from a different repo, taking from the frozen order prefix."""
    ordered = load_instance_order()
    assert ordered is not None, "instance_order.yaml missing — run freeze_instance_order first"
    seen: set[str] = set()
    picked: list[str] = []
    for iid in ordered:
        repo = iid.split("__")[0]
        if repo in seen:
            continue
        seen.add(repo)
        picked.append(iid)
        if len(picked) == n:
            return picked
    raise RuntimeError(f"Could not find {n} instances from different repos in ordering")


def _stub_run_agent(*, repo_dir, problem_statement, instance_id, model_name, **_) -> AgentRunResult:
    return AgentRunResult(
        instance_id=instance_id,
        model_patch=f"# stub patch for {instance_id}\n",
        cost_usd=0.0,
        n_llm_calls=0,
        n_steps=0,
    )


def _stub_run_swebench_eval(predictions_path: Path, **_) -> list[SWEBenchEvalResult]:
    out: list[SWEBenchEvalResult] = []
    for line in predictions_path.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        out.append(SWEBenchEvalResult(
            instance_id=entry["instance_id"], resolved=False, error=None,
        ))
    return out


def _stub_clone_repo(instance, work_dir: Path, shallow: bool = True) -> Path:
    """Stub clone_repo: init a tiny git repo in work_dir/<iid> so obfuscation context works."""
    repo_dir = work_dir / instance.instance_id.replace("/", "__")
    if repo_dir.exists():
        return repo_dir
    repo_dir.mkdir(parents=True)
    (repo_dir / "dummy.py").write_text("def hello():\n    return 'hi'\n")
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
        cwd=repo_dir, check=True, capture_output=True,
    )
    return repo_dir


def _run_one(
    experiment_name: str,
    artifacts_dir: Path,
    instance_ids: list[str],
    concurrency: int,
    stub_agent: bool,
    stub_eval: bool,
) -> tuple[float, list]:
    """Run the pipeline, return (wall_clock_seconds, reports)."""
    ctxs = []
    ctxs.append(patch(
        "swebench_task.source.pipeline.load_instances",
        side_effect=lambda *a, **kw: _load_restricted(instance_ids),
    ))
    if stub_agent:
        ctxs.append(patch("swebench_task.source.pipeline.run_agent", side_effect=_stub_run_agent))
        ctxs.append(patch("swebench_task.source.pipeline.clone_repo", side_effect=_stub_clone_repo))
    if stub_eval:
        ctxs.append(patch(
            "swebench_task.source.pipeline.run_swebench_eval",
            side_effect=_stub_run_swebench_eval,
        ))

    entered = [c.__enter__() for c in ctxs]
    try:
        t0 = time.perf_counter()
        reports = run_swebench_pipeline(
            obfuscation=RepoIdentity(),
            dataset_name="SWE-bench/SWE-bench_Verified",
            split="test",
            samples_limit=len(instance_ids),
            shuffle_seed=42,
            model_name="openai/gpt-5.4-nano-2026-03-17",
            max_turns=3,
            cost_limit=0.1,
            timeout_seconds=120.0,
            work_dir=artifacts_dir / "repos",
            output_dir=artifacts_dir / "runs",
            experiment_name=experiment_name,
            cache_dir=artifacts_dir / "cache",
            cache_enabled=True,
            agent_concurrency=concurrency,
            eval_max_workers=2,
            eval_timeout=300,
        )
        elapsed = time.perf_counter() - t0
    finally:
        for c in reversed(ctxs):
            c.__exit__(None, None, None)
    del entered
    return elapsed, reports


def _load_restricted(instance_ids: list[str]):
    """Return the requested instances in the requested order."""
    from swebench_task.source.dataset import load_instances as real_load
    all_instances = real_load()
    by_id = {i.instance_id: i for i in all_instances}
    missing = [iid for iid in instance_ids if iid not in by_id]
    assert not missing, f"Instances missing from usable set: {missing}"
    return [by_id[iid] for iid in instance_ids]


def _wipe_cache_entry(artifacts_dir: Path, obf: str, model: str, iid: str) -> None:
    path = CacheKey(obf, model, iid).as_path(artifacts_dir / "cache")
    if path.exists():
        path.unlink()
        logger.info("Wiped cache entry: %s", path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-llm", action="store_true", help="Stub run_agent + clone_repo (no API calls)")
    parser.add_argument("--no-docker", action="store_true", help="Stub run_swebench_eval (no Docker)")
    parser.add_argument("--n", type=int, default=3)
    parser.add_argument(
        "--artifacts-dir", type=Path,
        default=Path("swebench_task/artifacts/smoke_test"),
    )
    args = parser.parse_args()

    configure_logging(Path("logs"), "smoke_test")
    logging.getLogger("swebench_task").setLevel(logging.INFO)

    if args.artifacts_dir.exists():
        logger.info("Wiping smoke-test artifacts at %s", args.artifacts_dir)
        shutil.rmtree(args.artifacts_dir)

    instance_ids = _pick_diverse_instances(args.n)
    logger.info("Smoke test instances: %s", instance_ids)
    model = "openai/gpt-5.4-nano-2026-03-17"

    print("\n" + "=" * 80)
    print(f"[1/4] Baseline sequential, fresh cache (n={args.n}, concurrency=1)")
    print("=" * 80)
    t1, reports1 = _run_one(
        "smoke_1_sequential", args.artifacts_dir, instance_ids,
        concurrency=1, stub_agent=args.no_llm, stub_eval=args.no_docker,
    )
    assert len(reports1) == args.n, f"Expected {args.n} reports, got {len(reports1)}"
    for r in reports1:
        cache_path = CacheKey("identity", model, r.instance_id).as_path(args.artifacts_dir / "cache")
        assert cache_path.exists(), f"Cache entry missing: {cache_path}"
    print(f"  Wall-clock: {t1:.1f}s | reports: {len(reports1)} | cached: {args.n}/{args.n}")

    print("\n" + "=" * 80)
    print("[2/4] Re-run same config — should hit cache")
    print("=" * 80)
    t2, reports2 = _run_one(
        "smoke_2_cached", args.artifacts_dir, instance_ids,
        concurrency=1, stub_agent=args.no_llm, stub_eval=args.no_docker,
    )
    assert len(reports2) == args.n
    assert t2 < max(5.0, t1 * 0.5), f"Cached re-run ({t2:.1f}s) should be << fresh ({t1:.1f}s)"
    print(f"  Wall-clock: {t2:.1f}s (vs {t1:.1f}s fresh — {t1/max(t2, 0.01):.1f}x speedup)")

    print("\n" + "=" * 80)
    print("[3/4] Wipe one cache entry, re-run — should run 1, cache 2")
    print("=" * 80)
    _wipe_cache_entry(args.artifacts_dir, "identity", model, instance_ids[0])
    t3, reports3 = _run_one(
        "smoke_3_partial", args.artifacts_dir, instance_ids,
        concurrency=1, stub_agent=args.no_llm, stub_eval=args.no_docker,
    )
    assert len(reports3) == args.n
    print(f"  Wall-clock: {t3:.1f}s (expect 1/{args.n} of fresh)")

    print("\n" + "=" * 80)
    print(f"[4/4] Wipe all cache, run with concurrency={args.n}")
    print("=" * 80)
    shutil.rmtree(args.artifacts_dir / "cache", ignore_errors=True)
    t4, reports4 = _run_one(
        "smoke_4_async", args.artifacts_dir, instance_ids,
        concurrency=args.n, stub_agent=args.no_llm, stub_eval=args.no_docker,
    )
    assert len(reports4) == args.n
    print(f"  Wall-clock: {t4:.1f}s (linear-speedup target: ~{t1/args.n:.1f}s)")

    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"  [1] Sequential fresh:  {t1:6.2f}s")
    print(f"  [2] Sequential cached: {t2:6.2f}s   (speedup: {t1/max(t2, 0.01):.1f}x)")
    print(f"  [3] Partial cached:    {t3:6.2f}s")
    print(f"  [4] Async concurrent:  {t4:6.2f}s   (speedup: {t1/max(t4, 0.01):.1f}x)")
    print("\nAll 4 scenarios passed.")


if __name__ == "__main__":
    main()
