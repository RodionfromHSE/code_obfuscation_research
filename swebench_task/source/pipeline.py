"""SWE-bench pipeline: load instances -> cache-check -> obfuscate -> agent -> evaluate -> report."""
import asyncio
import dataclasses
import logging
import shutil
import sys
from pathlib import Path

from tqdm import tqdm

from swebench_task.agent.runner import AgentRunResult, run_agent
from swebench_task.evaluation.swebench_eval import (
    run_swebench_eval,
    save_predictions,
)
from swebench_task.obfuscation.protocol import RepoObfuscation
from swebench_task.obfuscation.repo_copy import obfuscated_repo
from swebench_task.source.async_runner import run_bounded_ordered
from swebench_task.source.cache import CacheKey, RunCache, has_reusable_eval_result
from swebench_task.source.dataset import SWEBenchInstance, clone_repo, load_instances
from swebench_task.utils.reporting import InstanceReport, save_instance_report, save_summary_report

logger = logging.getLogger(__name__)


def _run_agent_on_instance(
    instance: SWEBenchInstance,
    obfuscation: RepoObfuscation,
    work_dir: Path,
    reports_dir: Path,
    model_name: str,
    max_turns: int,
    cost_limit: float,
    timeout_seconds: float,
    api_base: str | None = None,
    cost_tracking: str = "default",
    shallow_clone: bool = True,
) -> tuple[AgentRunResult, InstanceReport]:
    repo_dir = clone_repo(instance, work_dir, shallow=shallow_clone)

    with obfuscated_repo(repo_dir, obfuscation) as ctx:
        agent_result = run_agent(
            repo_dir=ctx.obfuscated_dir,
            problem_statement=instance.problem_statement,
            instance_id=instance.instance_id,
            model_name=model_name,
            max_turns=max_turns,
            cost_limit=cost_limit,
            timeout_seconds=timeout_seconds,
            api_base=api_base,
            cost_tracking=cost_tracking,
        )
        clean_patch = obfuscation.deobfuscate_patch(agent_result.model_patch, ctx.result)
        agent_result = dataclasses.replace(agent_result, model_patch=clean_patch)
        obfuscation_result = ctx.result

    report = InstanceReport(
        instance_id=instance.instance_id,
        obfuscation_name=obfuscation.name,
        obfuscation=obfuscation_result,
        agent=agent_result,
    )
    save_instance_report(report, reports_dir)
    return agent_result, report


def _process_instance(
    instance: SWEBenchInstance,
    obfuscation: RepoObfuscation,
    work_dir: Path,
    reports_dir: Path,
    model_name: str,
    max_turns: int,
    cost_limit: float,
    timeout_seconds: float,
    api_base: str | None = None,
    cost_tracking: str = "default",
    shallow_clone: bool = True,
    cache: RunCache | None = None,
) -> tuple[AgentRunResult, InstanceReport, bool]:
    """Returns (agent_result, report, was_cached)."""
    if cache is not None:
        hit = cache.get(CacheKey(obfuscation.name, model_name, instance.instance_id))
        if hit is not None:
            save_instance_report(hit, reports_dir)
            tier = "full" if has_reusable_eval_result(hit) else "agent-only"
            logger.info("Cache hit (%s): %s (status=%s)", tier, instance.instance_id, hit.status())
            return hit.agent, hit, True

    agent_result, report = _run_agent_on_instance(
        instance=instance,
        obfuscation=obfuscation,
        work_dir=work_dir,
        reports_dir=reports_dir,
        model_name=model_name,
        max_turns=max_turns,
        cost_limit=cost_limit,
        timeout_seconds=timeout_seconds,
        api_base=api_base,
        cost_tracking=cost_tracking,
        shallow_clone=shallow_clone,
    )
    return agent_result, report, False


def _log_instance_progress(idx: int, total: int, report: InstanceReport, cached: bool) -> None:
    patch_len = len(report.agent.model_patch)
    obfus = report.obfuscation
    parts = [f"[{idx}/{total}] {report.instance_id}"]
    if cached:
        parts.append("CACHED")
    if obfus.symbols_renamed:
        parts.append(f"obfus={obfus.symbols_renamed}sym/{obfus.files_modified}files")
    if report.agent.error:
        parts.append(f"agent_error={report.agent.error[:80]}")
    elif report.agent.timed_out:
        parts.append("TIMEOUT")
    else:
        parts.append(f"patch={patch_len}chars")
    logger.info(" | ".join(parts))


def _run_agent_phase_sequential(
    instances: list[SWEBenchInstance],
    process_fn,
) -> list[tuple[AgentRunResult, InstanceReport, bool]]:
    out = []
    for idx, inst in enumerate(
        tqdm(instances, desc="Agents", unit="inst", file=sys.stdout), 1,
    ):
        res = process_fn(inst)
        _log_instance_progress(idx, len(instances), res[1], res[2])
        out.append(res)
    return out


def _run_agent_phase_concurrent(
    instances: list[SWEBenchInstance],
    process_fn,
    concurrency: int,
) -> list[tuple[AgentRunResult, InstanceReport, bool]]:
    logger.info("Running %d agents with concurrency=%d (asyncio)", len(instances), concurrency)

    def _on_complete(done: int, total: int, _inst, res) -> None:
        _, report, cached = res
        _log_instance_progress(done, total, report, cached)

    return asyncio.run(
        run_bounded_ordered(
            instances, process_fn,
            concurrency=concurrency, desc="Agents",
            on_complete=_on_complete,
        )
    )


def run_swebench_pipeline(
    obfuscation: RepoObfuscation,
    dataset_name: str = "SWE-bench/SWE-bench_Verified",
    split: str = "test",
    samples_limit: int | None = None,
    shuffle_seed: int | None = 42,
    model_name: str = "openai/gpt-5.4-nano-2026-03-17",
    max_turns: int = 50,
    cost_limit: float = 3.0,
    timeout_seconds: float = 1200.0,
    work_dir: Path = Path("swebench_task/artifacts/repos"),
    output_dir: Path = Path("swebench_task/artifacts/runs"),
    experiment_name: str = "swebench_run",
    api_base: str | None = None,
    cost_tracking: str = "default",
    cache_dir: Path | None = None,
    cache_enabled: bool = True,
    cache_read_only: bool = False,
    agent_concurrency: int = 1,
    eval_max_workers: int = 4,
    eval_timeout: int = 1800,
    shallow_clone: bool = True,
    priority_ids: list[str] | None = None,
) -> list[InstanceReport]:
    """Run the full SWE-bench pipeline."""
    instances = load_instances(
        dataset_name, split, samples_limit,
        shuffle_seed=shuffle_seed, priority_ids=priority_ids,
    )
    work_dir.mkdir(parents=True, exist_ok=True)

    run_dir = output_dir / experiment_name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    reports_dir = run_dir / "instance_reports"

    cache = RunCache(
        cache_dir=cache_dir or (output_dir.parent / "cache"),
        enabled=cache_enabled,
        read_only=cache_read_only,
    )

    logger.info(
        "Pipeline: %d instances, obfuscation=%s, model=%s, concurrency=%d, cache=%s",
        len(instances), obfuscation.name, model_name, agent_concurrency,
        "on" if cache_enabled else "off",
    )

    def _process(inst: SWEBenchInstance):
        return _process_instance(
            instance=inst,
            obfuscation=obfuscation,
            work_dir=work_dir,
            reports_dir=reports_dir,
            model_name=model_name,
            max_turns=max_turns,
            cost_limit=cost_limit,
            timeout_seconds=timeout_seconds,
            api_base=api_base,
            cost_tracking=cost_tracking,
            shallow_clone=shallow_clone,
            cache=cache,
        )

    if agent_concurrency > 1:
        phase_results = _run_agent_phase_concurrent(instances, _process, agent_concurrency)
    else:
        phase_results = _run_agent_phase_sequential(instances, _process)

    all_reports = [r[1] for r in phase_results]

    for report in all_reports:
        cache.put(CacheKey(obfuscation.name, model_name, report.instance_id), report)

    needs_eval = [
        (r, inst) for r, inst in zip(all_reports, instances)
        if r.agent.model_patch and not has_reusable_eval_result(r)
    ]
    n_eval_cached = sum(1 for r in all_reports if has_reusable_eval_result(r))
    logger.info(
        "Eval phase: %d total, %d with cached eval, %d to run through Docker",
        len(all_reports), n_eval_cached, len(needs_eval),
    )

    eval_agent_results = [r.agent for r, _ in needs_eval]
    predictions_path = output_dir / experiment_name / "predictions.jsonl"
    save_predictions(eval_agent_results, predictions_path, model_name)

    if eval_agent_results:
        logger.info("Running SWE-bench evaluation (Docker)...")
        try:
            eval_results = run_swebench_eval(
                predictions_path=predictions_path,
                dataset_name=dataset_name,
                run_id=experiment_name,
                max_workers=eval_max_workers,
                timeout=eval_timeout,
                total_to_eval=len(eval_agent_results),
                report_dir=run_dir,
            )
            eval_map = {r.instance_id: r for r in eval_results}
            for report in all_reports:
                if report.instance_id in eval_map:
                    report.eval_result = eval_map[report.instance_id]
                    cache.put(CacheKey(obfuscation.name, model_name, report.instance_id), report)
        except Exception as e:
            logger.error("SWE-bench evaluation failed: %s", e)

    for report in all_reports:
        save_instance_report(report, reports_dir)

    summary_path = output_dir / experiment_name / "summary.json"
    save_summary_report(all_reports, summary_path)
    return all_reports
