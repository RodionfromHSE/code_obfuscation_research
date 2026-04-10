"""Wrapper around swebench evaluation harness."""
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from swe_task.agent.runner import AgentRunResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SWEBenchEvalResult:
    instance_id: str
    resolved: bool
    error: str | None = None


def save_predictions(
    results: list[AgentRunResult],
    output_path: Path,
    model_name: str,
) -> Path:
    """Write predictions in SWE-bench JSONL format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for r in results:
            entry = {
                "instance_id": r.instance_id,
                "model_name_or_path": model_name,
                "model_patch": r.model_patch,
            }
            f.write(json.dumps(entry) + "\n")
    logger.info("Saved %d predictions to %s", len(results), output_path)
    return output_path


def run_swebench_eval(
    predictions_path: Path,
    dataset_name: str = "SWE-bench/SWE-bench_Verified",
    split: str = "test",
    max_workers: int = 4,
    run_id: str = "eval",
    timeout: int = 1800,
) -> list[SWEBenchEvalResult]:
    """Run swebench eval harness and parse results."""
    from swebench.harness.run_evaluation import main as run_evaluation

    logger.info("Running SWE-bench evaluation on %s", predictions_path)
    try:
        run_evaluation(
            dataset_name=dataset_name,
            split=split,
            instance_ids=[],
            predictions_path=str(predictions_path),
            max_workers=max_workers,
            force_rebuild=False,
            cache_level="env",
            clean=False,
            open_file_limit=4096,
            run_id=run_id,
            timeout=timeout,
            namespace=None,
            rewrite_reports=False,
            modal=False,
        )
    except Exception as e:
        logger.error("SWE-bench evaluation failed: %s", e)
        return [SWEBenchEvalResult(instance_id="__global__", resolved=False, error=str(e))]

    # swebench writes per-instance reports under logs/run_evaluation/<run_id>/
    logs_dir = Path("logs") / "run_evaluation" / run_id
    per_instance = _parse_instance_reports(logs_dir)

    # also parse the global report for error_ids (Docker build failures)
    global_report = _find_global_report(predictions_path.parent, run_id)
    if global_report:
        per_instance = _merge_global_errors(per_instance, global_report)

    return per_instance


def _parse_instance_reports(results_dir: Path) -> list[SWEBenchEvalResult]:
    """Parse per-instance report.json files from swebench eval logs."""
    results: list[SWEBenchEvalResult] = []

    for report_file in results_dir.rglob("report.json"):
        try:
            data = json.loads(report_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to parse %s: %s", report_file, e)
            continue

        if isinstance(data, dict):
            for instance_id, status in data.items():
                resolved = status.get("resolved", False) if isinstance(status, dict) else bool(status)
                results.append(SWEBenchEvalResult(instance_id=instance_id, resolved=resolved))

    logger.info("Parsed %d per-instance eval results from %s", len(results), results_dir)
    return results


def _find_global_report(output_dir: Path, run_id: str) -> dict | None:
    """Find and parse the global swebench summary report."""
    # swebench writes to CWD as <model_name>.<run_id>.json
    for f in Path(".").glob(f"*.{run_id}.json"):
        try:
            return json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
    # also check output_dir
    for f in output_dir.glob(f"*.{run_id}.json"):
        try:
            return json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _merge_global_errors(
    per_instance: list[SWEBenchEvalResult],
    global_report: dict,
) -> list[SWEBenchEvalResult]:
    """Add eval_error results for instances that failed during Docker eval (build errors etc.)."""
    known_ids = {r.instance_id for r in per_instance}
    error_ids = set(global_report.get("error_ids", []))
    new_errors = error_ids - known_ids

    if new_errors:
        logger.info("Found %d eval errors from global report (Docker build failures)", len(new_errors))

    for iid in sorted(new_errors):
        per_instance.append(SWEBenchEvalResult(
            instance_id=iid,
            resolved=False,
            error="docker_build_failure",
        ))

    return per_instance
