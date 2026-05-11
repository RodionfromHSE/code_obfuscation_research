"""Global, cross-experiment cache of per-instance results.

Path key = (obfuscation_name, model_name, instance_id).
Validation key = deterministic run fingerprint stored inside the JSON.

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
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from swebench_task.agent.runner import AgentRunResult
from swebench_task.evaluation.swebench_eval import SWEBenchEvalResult
from swebench_task.obfuscation.protocol import RepoObfuscation, RepoObfuscationResult
from swebench_task.source.dataset import SWEBenchInstance
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
    fingerprint: str | None = None

    def as_path(self, root: Path) -> Path:
        safe_model = self.model_name.replace("/", "__")
        safe_iid = self.instance_id.replace("/", "__")
        return root / self.obfuscation_name / safe_model / f"{safe_iid}.json"


def build_cache_key(
    instance: SWEBenchInstance,
    obfuscation: RepoObfuscation,
    dataset_name: str,
    split: str,
    model_name: str,
    max_turns: int,
    cost_limit: float,
    timeout_seconds: float,
    api_base: str | None,
    cost_tracking: str,
) -> CacheKey:
    payload = {
        "version": 2,
        "dataset": {
            "name": dataset_name,
            "split": split,
        },
        "instance": {
            "instance_id": instance.instance_id,
            "repo": instance.repo,
            "base_commit": instance.base_commit,
            "problem_sha256": hashlib.sha256(
                instance.problem_statement.encode()
            ).hexdigest(),
        },
        "obfuscation": _obfuscation_state(obfuscation),
        "agent": {
            "model_name": model_name,
            "max_turns": max_turns,
            "cost_limit": cost_limit,
            "timeout_seconds": timeout_seconds,
            "api_base": api_base,
            "cost_tracking": cost_tracking,
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return CacheKey(
        obfuscation_name=obfuscation.name,
        model_name=model_name,
        instance_id=instance.instance_id,
        fingerprint=hashlib.sha256(raw.encode()).hexdigest(),
    )


def _jsonable(value):
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(k): _jsonable(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, set | frozenset):
        return [_jsonable(v) for v in sorted(value, key=repr)]
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    return repr(value)


def _obfuscation_state(obfuscation: RepoObfuscation) -> dict:
    return {
        "class": f"{type(obfuscation).__module__}.{type(obfuscation).__qualname__}",
        "attrs": _public_attrs(obfuscation),
    }


def _public_attrs(obj) -> dict:
    names = set(getattr(obj, "__dict__", {}).keys())
    for cls in type(obj).mro():
        slots = getattr(cls, "__slots__", ())
        if isinstance(slots, str):
            names.add(slots)
        else:
            names.update(slots)
    return {
        name: _jsonable(getattr(obj, name))
        for name in sorted(names)
        if not name.startswith("_") and hasattr(obj, name)
    }


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
            data = _load_report_data(path)
        except Exception as e:
            logger.warning("Cache read failed for %s: %s", path, e)
            return None
        if not _matches_key(data, key):
            logger.debug("Cache entry ignored because key metadata is stale: %s", path)
            return None
        report = _report_from_data(data)
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
        atomic_write_text(path, _dump_report(report, key.fingerprint))
        logger.debug("Cached %s (status=%s) -> %s", key.instance_id, report.status(), path)


def _dump_report(report: InstanceReport, fingerprint: str | None = None) -> str:
    data = {
        "cache_fingerprint": fingerprint,
        "instance_id": report.instance_id,
        "obfuscation_name": report.obfuscation_name,
        "status": report.status(),
        "obfuscation": dataclasses.asdict(report.obfuscation),
        "agent": dataclasses.asdict(report.agent),
        "eval": dataclasses.asdict(report.eval_result) if report.eval_result else None,
    }
    return json.dumps(data, indent=2)


def _load_report_data(path: Path) -> dict:
    return json.loads(path.read_text())


def _matches_key(data: dict, key: CacheKey) -> bool:
    if data.get("instance_id") != key.instance_id:
        return False
    if data.get("obfuscation_name") != key.obfuscation_name:
        return False
    agent = data.get("agent") or {}
    if agent.get("instance_id") != key.instance_id:
        return False
    if key.fingerprint is not None and data.get("cache_fingerprint") != key.fingerprint:
        return False
    return True


def _report_from_data(data: dict) -> InstanceReport:
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
