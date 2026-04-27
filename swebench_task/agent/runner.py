"""Wrapper around mini-swe-agent for running a single SWE-bench instance."""
import functools
import importlib.resources
import logging
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MSWEA_SILENT_STARTUP", "1")
os.environ.setdefault("LITELLM_LOG", "ERROR")

import litellm  # noqa: E402
import yaml  # noqa: E402
from minisweagent.agents.default import DefaultAgent  # noqa: E402
from minisweagent.environments.local import LocalEnvironment  # noqa: E402
from minisweagent.models.litellm_model import LitellmModel  # noqa: E402

from swebench_task.utils.litellm_setup import register_model_cost  # noqa: E402

litellm.suppress_debug_info = True

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Outcome of running the agent on one SWE-bench instance."""

    instance_id: str
    model_patch: str
    timed_out: bool = False
    error: str | None = None
    cost_usd: float = 0.0
    n_llm_calls: int = 0
    n_steps: int = 0


@functools.cache
def _load_default_templates() -> dict[str, str]:
    """Load system_template and instance_template from mini-swe-agent defaults.

    Cached: templates are identical across all instances in a run.
    """
    config_dir = importlib.resources.files("minisweagent") / "config" / "default.yaml"
    config = yaml.safe_load(config_dir.read_text())
    agent_cfg = config["agent"]
    return {
        "system_template": agent_cfg["system_template"],
        "instance_template": agent_cfg["instance_template"],
    }


def _git_diff(repo_dir: Path) -> str:
    """Get the unified diff of all changes in the repo."""
    result = subprocess.run(
        ["git", "diff"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


@dataclass
class _AgentStats:
    cost: float = 0.0
    n_calls: int = 0
    n_steps: int = 0


def _run_agent_inner(
    repo_dir: Path,
    problem_statement: str,
    model_name: str,
    max_turns: int,
    cost_limit: float,
    stats: _AgentStats,
    api_base: str | None = None,
    cost_tracking: str = "default",
) -> None:
    templates = _load_default_templates()
    model_kwargs: dict[str, str] = {}
    if api_base:
        model_kwargs["api_base"] = api_base
    model = LitellmModel(
        model_name=model_name,
        model_kwargs=model_kwargs,
        cost_tracking=cost_tracking,
    )
    env = LocalEnvironment(cwd=str(repo_dir))
    agent = DefaultAgent(
        model=model,
        env=env,
        step_limit=max_turns,
        cost_limit=cost_limit,
        **templates,
    )
    agent.run(problem_statement)
    stats.cost = getattr(agent, "cost", 0.0)
    stats.n_calls = getattr(agent, "n_calls", 0)
    stats.n_steps = sum(1 for m in agent.messages if m.get("role") == "assistant")


def run_agent(
    repo_dir: Path,
    problem_statement: str,
    instance_id: str,
    model_name: str = "openai/gpt-5.4-nano-2026-03-17",
    max_turns: int = 50,
    cost_limit: float = 3.0,
    timeout_seconds: float = 1200.0,
    api_base: str | None = None,
    cost_tracking: str = "default",
) -> AgentRunResult:
    """Run mini-swe-agent on a repo and return the generated patch."""
    logger.debug("Running agent on %s (model=%s, max_turns=%d, timeout=%.0fs)",
                 instance_id, model_name, max_turns, timeout_seconds)

    register_model_cost(model_name)
    stats = _AgentStats()

    # not using `with ThreadPoolExecutor` on purpose: its __exit__ calls
    # shutdown(wait=True), which defeats the timeout by blocking until the
    # worker finishes. on timeout we shutdown(wait=False) and let the
    # orphan thread finish on its own — python can't kill threads, but
    # cost_limit + step_limit inside DefaultAgent.query() are the real
    # budget guards; timeout_seconds is a belt-and-suspenders wall-clock.
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"agent-{instance_id}")
    future = executor.submit(
        _run_agent_inner, repo_dir, problem_statement, model_name, max_turns, cost_limit, stats,
        api_base=api_base, cost_tracking=cost_tracking,
    )
    try:
        future.result(timeout=timeout_seconds)
    except FuturesTimeoutError:
        executor.shutdown(wait=False, cancel_futures=True)
        logger.warning("Agent timed out after %.0fs on %s", timeout_seconds, instance_id)
        return AgentRunResult(
            instance_id=instance_id,
            model_patch="",
            timed_out=True,
            error=f"timeout after {timeout_seconds}s",
            cost_usd=stats.cost,
            n_llm_calls=stats.n_calls,
            n_steps=stats.n_steps,
        )
    except Exception as e:
        executor.shutdown(wait=False, cancel_futures=True)
        logger.error("Agent error on %s: %s", instance_id, e)
        return AgentRunResult(
            instance_id=instance_id,
            model_patch="",
            error=str(e),
            cost_usd=stats.cost,
            n_llm_calls=stats.n_calls,
            n_steps=stats.n_steps,
        )
    executor.shutdown(wait=True)

    patch = _git_diff(repo_dir)
    logger.debug("Agent finished %s: patch=%d chars, cost=$%.4f, calls=%d, steps=%d",
                 instance_id, len(patch), stats.cost, stats.n_calls, stats.n_steps)

    return AgentRunResult(
        instance_id=instance_id,
        model_patch=patch,
        cost_usd=stats.cost,
        n_llm_calls=stats.n_calls,
        n_steps=stats.n_steps,
    )
