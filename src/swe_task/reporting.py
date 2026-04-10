"""Per-instance and summary reporting for SWE-bench runs."""
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from swe_task.agent.runner import AgentRunResult
from swe_task.evaluation.swebench_eval import SWEBenchEvalResult
from swe_task.obfuscation.protocol import RepoObfuscationResult

logger = logging.getLogger(__name__)


@dataclass
class InstanceReport:
    """Full report for a single SWE-bench instance."""

    instance_id: str
    obfuscation_name: str
    obfuscation: RepoObfuscationResult
    agent: AgentRunResult
    eval_result: SWEBenchEvalResult | None = None

    def status(self) -> str:
        if self.agent.error and not self.agent.timed_out:
            return "agent_error"
        if self.agent.timed_out:
            return "agent_timeout"
        if not self.agent.model_patch:
            return "empty_patch"
        if self.eval_result is None:
            return "not_evaluated"
        if self.eval_result.error:
            return "eval_error"
        return "resolved" if self.eval_result.resolved else "failed"


def save_instance_report(report: InstanceReport, reports_dir: Path) -> Path:
    """Save a single instance report as JSON."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{report.instance_id.replace('/', '__')}.json"
    data = {
        "instance_id": report.instance_id,
        "status": report.status(),
        "obfuscation_name": report.obfuscation_name,
        "obfuscation": asdict(report.obfuscation),
        "agent": asdict(report.agent),
        "eval": asdict(report.eval_result) if report.eval_result else None,
    }
    path.write_text(json.dumps(data, indent=2))
    logger.debug("Saved instance report to %s", path)
    return path


def save_summary_report(reports: list[InstanceReport], output_path: Path) -> Path:
    """Save a summary report with aggregate stats."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    statuses = [r.status() for r in reports]
    total = len(reports)
    resolved = statuses.count("resolved")
    failed = statuses.count("failed")
    agent_errors = statuses.count("agent_error")
    timeouts = statuses.count("agent_timeout")
    empty = statuses.count("empty_patch")
    eval_errors = statuses.count("eval_error")
    not_evaluated = statuses.count("not_evaluated")

    # only count instances that swebench actually evaluated
    evaluated = resolved + failed
    resolve_rate_evaluated = resolved / evaluated if evaluated else 0.0

    patch_sizes = [len(r.agent.model_patch) for r in reports if r.agent.model_patch]
    obfus_errors = sum(1 for r in reports if r.obfuscation.errors)
    total_cost = sum(r.agent.cost_usd for r in reports)
    total_calls = sum(r.agent.n_llm_calls for r in reports)

    summary = {
        "total_instances": total,
        "evaluated": evaluated,
        "resolved": resolved,
        "resolved_rate_of_evaluated": round(resolve_rate_evaluated, 4),
        "resolved_rate_of_total": round(resolved / total, 4) if total else 0,
        "failed": failed,
        "agent_errors": agent_errors,
        "agent_timeouts": timeouts,
        "empty_patches": empty,
        "eval_errors": eval_errors,
        "not_evaluated": not_evaluated,
        "obfuscation_name": reports[0].obfuscation_name if reports else "unknown",
        "avg_symbols_renamed": round(
            sum(r.obfuscation.symbols_renamed for r in reports) / total, 1
        ) if total else 0,
        "obfuscation_had_errors": obfus_errors,
        "cost": {
            "total_usd": round(total_cost, 4),
            "per_instance_usd": round(total_cost / total, 4) if total else 0,
            "total_llm_calls": total_calls,
        },
        "patch_stats": {
            "non_empty": len(patch_sizes),
            "median": round(sorted(patch_sizes)[len(patch_sizes) // 2]) if patch_sizes else 0,
            "mean": round(sum(patch_sizes) / len(patch_sizes)) if patch_sizes else 0,
            "max": max(patch_sizes) if patch_sizes else 0,
        },
        "instances": [
            {"instance_id": r.instance_id, "status": r.status()}
            for r in reports
        ],
    }

    output_path.write_text(json.dumps(summary, indent=2))

    logger.info(
        "Summary: %d evaluated, %d/%d resolved (%.1f%% of evaluated), "
        "%d failed, %d empty_patch, %d eval_errors, %d agent_errors, %d timeouts",
        evaluated, resolved, total, resolve_rate_evaluated * 100,
        failed, empty, eval_errors, agent_errors, timeouts,
    )
    return output_path
