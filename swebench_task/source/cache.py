"""Global, cross-experiment cache of per-instance results.

Key = (obfuscation_name, model_name, instance_id).

Two-tier reuse:
    - Agent reuse:  agent ran to completion (any of resolved/failed/empty_patch/
                    agent_timeout/not_evaluated). Cached regardless of eval outcome,
                    because the agent phase is the expensive LLM-cost piece.
    - Eval reuse:   eval_result present and has no error. When the cache hit has
                    an invalid eval_result, the pipeline re-runs only the Docker
                    eval step and updates the cached entry.

Statuses NEVER cached (transient / non-deterministic):
    - agent_error   (could be a network hiccup)
    - eval_error    (Docker OOM, network, etc.)
"""
import dataclasses
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from swebench_task.agent.runner import AgentRunResult
from swebench_task.evaluation.swebench_eval import SWEBenchEvalResult
from swebench_task.obfuscation.protocol import RepoObfuscationResult
from swebench_task.utils.reporting import InstanceReport, atomic_write_text

logger = logging.getLogger(__name__)

_AGENT_COMPLETED_STATUSES = frozenset({
    "resolved", "failed", "empty_patch", "agent_timeout", "not_evaluated",
})


@dataclass(frozen=True, slots=True)
class CacheKey:
    obfuscation_name: str
    model_name: str
    instance_id: str

    def as_path(self, root: Path) -> Path:
        safe_model = self.model_name.replace("/", "__")
        safe_iid = self.instance_id.replace("/", "__")
        return root / self.obfuscation_name / safe_model / f"{safe_iid}.json"


def has_reusable_agent_result(report: InstanceReport) -> bool:
    """True when the agent ran to completion; safe to skip agent phase on re-run."""
    return report.status() in _AGENT_COMPLETED_STATUSES


def has_reusable_eval_result(report: InstanceReport) -> bool:
    """True when eval has a clean result; safe to skip Docker eval on re-run."""
    return report.eval_result is not None and not report.eval_result.error


class RunCache:
    """Read/write cache of InstanceReport JSONs keyed by CacheKey."""

    def __init__(self, cache_dir: Path, enabled: bool = True, read_only: bool = False):
        self.cache_dir = cache_dir
        self.enabled = enabled
        self.read_only = read_only
        if enabled:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: CacheKey) -> InstanceReport | None:
        """Return cached report if present AND its agent phase is reusable.

        The returned report may or may not have a valid `eval_result` — callers
        should check `has_reusable_eval_result()` before skipping the eval phase.
        """
        if not self.enabled:
            return None
        path = key.as_path(self.cache_dir)
        if not path.exists():
            return None
        try:
            report = _load_report(path)
        except Exception as e:
            logger.warning("Cache read failed for %s: %s", path, e)
            return None
        if not has_reusable_agent_result(report):
            return None
        return report

    def put(self, key: CacheKey, report: InstanceReport) -> None:
        """Write report to cache iff agent phase completed.

        Safe to call multiple times — each call overwrites the prior entry, so
        the post-eval call strictly enriches the agent-only entry.
        """
        if not self.enabled or self.read_only:
            return
        if not has_reusable_agent_result(report):
            return
        path = key.as_path(self.cache_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, _dump_report(report))
        logger.debug("Cached %s (status=%s) -> %s", key.instance_id, report.status(), path)


def _dump_report(report: InstanceReport) -> str:
    data = {
        "instance_id": report.instance_id,
        "obfuscation_name": report.obfuscation_name,
        "status": report.status(),
        "obfuscation": dataclasses.asdict(report.obfuscation),
        "agent": dataclasses.asdict(report.agent),
        "eval": dataclasses.asdict(report.eval_result) if report.eval_result else None,
    }
    return json.dumps(data, indent=2)


def _load_report(path: Path) -> InstanceReport:
    data = json.loads(path.read_text())
    obfus = RepoObfuscationResult(**data["obfuscation"])
    agent = AgentRunResult(**data["agent"])
    eval_data = data.get("eval")
    eval_result = SWEBenchEvalResult(**eval_data) if eval_data else None
    return InstanceReport(
        instance_id=data["instance_id"],
        obfuscation_name=data["obfuscation_name"],
        obfuscation=obfus,
        agent=agent,
        eval_result=eval_result,
    )
