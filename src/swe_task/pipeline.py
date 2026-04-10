"""SWE-bench pipeline: load instances -> obfuscate -> run agent -> evaluate -> report."""
import dataclasses
import logging
import sys
from pathlib import Path

from tqdm import tqdm

from swe_task.agent.runner import AgentRunResult, run_agent
from swe_task.dataset import SWEBenchInstance, clone_repo, load_instances
from swe_task.evaluation.swebench_eval import (
    run_swebench_eval,
    save_predictions,
)
from swe_task.obfuscation.protocol import RepoObfuscation
from swe_task.obfuscation.repo_copy import obfuscated_repo
from swe_task.reporting import InstanceReport, save_instance_report, save_summary_report

logger = logging.getLogger(__name__)


def _process_instance(
    instance: SWEBenchInstance,
    obfuscation: RepoObfuscation,
    work_dir: Path,
    reports_dir: Path,
    model_name: str,
    max_turns: int,
    cost_limit: float,
    timeout_seconds: float,
) -> tuple[AgentRunResult, InstanceReport]:
    repo_dir = clone_repo(instance, work_dir)

    with obfuscated_repo(repo_dir, obfuscation) as ctx:
        agent_result = run_agent(
            repo_dir=ctx.obfuscated_dir,
            problem_statement=instance.problem_statement,
            instance_id=instance.instance_id,
            model_name=model_name,
            max_turns=max_turns,
            cost_limit=cost_limit,
            timeout_seconds=timeout_seconds,
        )
        clean_patch = obfuscation.deobfuscate_patch(
            agent_result.model_patch, ctx.result,
        )
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


def _log_instance_progress(idx: int, total: int, report: InstanceReport) -> None:
    patch_len = len(report.agent.model_patch)
    obfus = report.obfuscation
    parts = [f"[{idx}/{total}] {report.instance_id}"]
    if obfus.symbols_renamed:
        parts.append(f"obfus={obfus.symbols_renamed}sym/{obfus.files_modified}files")
    if report.agent.error:
        parts.append(f"agent_error={report.agent.error[:80]}")
    elif report.agent.timed_out:
        parts.append("TIMEOUT")
    else:
        parts.append(f"patch={patch_len}chars")
    logger.info(" | ".join(parts))


def run_swebench_pipeline(
    obfuscation: RepoObfuscation,
    dataset_name: str = "SWE-bench/SWE-bench_Verified",
    split: str = "test",
    samples_limit: int | None = None,
    model_name: str = "openai/gpt-5.4-nano-2026-03-17",
    max_turns: int = 50,
    cost_limit: float = 3.0,
    timeout_seconds: float = 1200.0,
    work_dir: Path = Path("artifacts/swebench/repos"),
    output_dir: Path = Path("artifacts/swebench/runs"),
    experiment_name: str = "swebench_run",
) -> list[InstanceReport]:
    """Run the full SWE-bench pipeline."""
    instances = load_instances(dataset_name, split, samples_limit)
    work_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Pipeline: %d instances, obfuscation=%s, model=%s",
                len(instances), obfuscation.name, model_name)

    reports_dir = output_dir / experiment_name / "instance_reports"
    agent_results: list[AgentRunResult] = []
    all_reports: list[InstanceReport] = []

    for idx, instance in enumerate(tqdm(instances, desc="SWE-bench", unit="inst", file=sys.stdout), 1):
        agent_result, report = _process_instance(
            instance=instance,
            obfuscation=obfuscation,
            work_dir=work_dir,
            reports_dir=reports_dir,
            model_name=model_name,
            max_turns=max_turns,
            cost_limit=cost_limit,
            timeout_seconds=timeout_seconds,
        )
        agent_results.append(agent_result)
        all_reports.append(report)
        _log_instance_progress(idx, len(instances), report)

    predictions_path = output_dir / experiment_name / "predictions.jsonl"
    save_predictions(agent_results, predictions_path, model_name)

    logger.info("Running SWE-bench evaluation (Docker)...")
    try:
        eval_results = run_swebench_eval(
            predictions_path=predictions_path,
            dataset_name=dataset_name,
            run_id=experiment_name,
        )
        eval_map = {r.instance_id: r for r in eval_results}
        for report in all_reports:
            report.eval_result = eval_map.get(report.instance_id)
    except Exception as e:
        logger.error("SWE-bench evaluation failed (Docker may not be running): %s", e)

    for report in all_reports:
        save_instance_report(report, reports_dir)

    summary_path = output_dir / experiment_name / "summary.json"
    save_summary_report(all_reports, summary_path)

    return all_reports
