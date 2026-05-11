"""Wrapper around mini-swe-agent for running a single SWE-bench instance."""
import importlib.resources
import json
import logging
import os
import re
import subprocess
import time
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
from minisweagent.exceptions import FormatError  # noqa: E402
from minisweagent.models.litellm_model import LitellmModel  # noqa: E402

from swebench_task.utils.litellm_setup import register_model_costs  # noqa: E402

litellm.suppress_debug_info = True
register_model_costs()

logger = logging.getLogger(__name__)

_BASH_BLOCK_RE = re.compile(r"```mswea_bash_command\s*\n(.*?)```", re.DOTALL)
_SUDO_RE = re.compile(r"(^|[;&|]\s*)sudo(\s|$)")
_BLOCKED_COMMAND_PATTERNS = (
    "/path/to/working/dir",
    "/usr/lib/",
    "/usr/local/lib/",
    "/site-packages/",
)
_SWE_SYSTEM_APPENDIX = """

Additional SWE-bench rules:
- Work only inside the current repository checkout.
- Do not use sudo; this environment is non-interactive and sudo will fail.
- Do not edit system Python, site-packages, virtualenv internals, or files outside the repository.
- Fix the checked-out project files and verify with local commands.
"""


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
    transcript_path: str | None = None
    raw_responses_path: str | None = None


def _load_default_templates() -> dict[str, str]:
    """Load system_template and instance_template from mini-swe-agent defaults."""
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


def _safe_instance_filename(instance_id: str) -> str:
    """Convert a SWE-bench instance id into a filesystem-safe JSON filename."""
    return instance_id.replace("/", "__") + ".json"


class TranscriptLitellmModel(LitellmModel):
    """LitellmModel variant that persists raw API responses before action parsing."""

    def __init__(self, *args, raw_responses_path: Path | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.raw_responses_path = raw_responses_path

    def _parse_actions(self, response) -> list[dict]:
        self._append_raw_response(response)
        try:
            return super()._parse_actions(response)
        except FormatError:
            actions = self._parse_bash_block_actions(response)
            if actions:
                return actions
            raise

    def _parse_bash_block_actions(self, response) -> list[dict]:
        content = response.choices[0].message.content or ""
        matches = _BASH_BLOCK_RE.findall(content)
        if len(matches) != 1:
            return []
        command = matches[0].strip()
        if not command:
            return []
        return [{"command": command}]

    def _append_raw_response(self, response) -> None:
        if self.raw_responses_path is None:
            return
        self.raw_responses_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": time.time(),
            "response": response.model_dump(),
        }
        with self.raw_responses_path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")


class GuardedLocalEnvironment(LocalEnvironment):
    """LocalEnvironment that rejects commands known to hang or edit outside the repo."""

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict:
        command = action.get("command", "")
        blocked_reason = _blocked_command_reason(command)
        if blocked_reason:
            return {
                "output": blocked_reason,
                "returncode": 2,
                "exception_info": "",
            }
        return super().execute(action, cwd=cwd, timeout=timeout)


def _blocked_command_reason(command: str) -> str:
    if _SUDO_RE.search(command):
        return (
            "Blocked command: sudo is not available in this non-interactive environment. "
            "Edit repository files directly."
        )
    for pattern in _BLOCKED_COMMAND_PATTERNS:
        if pattern in command:
            return (
                "Blocked command: operate only inside the current repository checkout; "
                f"do not target {pattern}."
            )
    return ""


def _run_agent_inner(
    repo_dir: Path,
    problem_statement: str,
    model_name: str,
    max_turns: int,
    cost_limit: float,
    stats: _AgentStats,
    api_base: str | None = None,
    cost_tracking: str = "default",
    transcript_path: Path | None = None,
    raw_responses_path: Path | None = None,
) -> None:
    templates = _load_default_templates()
    templates["system_template"] = templates["system_template"].rstrip() + _SWE_SYSTEM_APPENDIX
    model_kwargs: dict[str, str] = {}
    if api_base:
        model_kwargs["api_base"] = api_base
    model = TranscriptLitellmModel(
        model_name=model_name,
        model_kwargs=model_kwargs,
        cost_tracking=cost_tracking,
        raw_responses_path=raw_responses_path,
    )
    env = GuardedLocalEnvironment(cwd=str(repo_dir))
    agent = DefaultAgent(
        model=model,
        env=env,
        step_limit=max_turns,
        cost_limit=cost_limit,
        output_path=transcript_path,
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
    transcripts_dir: Path | None = None,
    raw_responses_dir: Path | None = None,
) -> AgentRunResult:
    """Run mini-swe-agent on a repo and return the generated patch."""
    logger.debug("Running agent on %s (model=%s, max_turns=%d, timeout=%.0fs)",
                 instance_id, model_name, max_turns, timeout_seconds)

    stats = _AgentStats()
    transcript_path = (
        transcripts_dir / _safe_instance_filename(instance_id)
        if transcripts_dir is not None
        else None
    )
    raw_responses_path = (
        raw_responses_dir / _safe_instance_filename(instance_id).replace(".json", ".jsonl")
        if raw_responses_dir is not None
        else None
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            _run_agent_inner, repo_dir, problem_statement, model_name, max_turns, cost_limit, stats,
            api_base=api_base, cost_tracking=cost_tracking, transcript_path=transcript_path,
            raw_responses_path=raw_responses_path,
        )
        try:
            future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            logger.warning("Agent timed out after %.0fs on %s", timeout_seconds, instance_id)
            return AgentRunResult(
                instance_id=instance_id,
                model_patch="",
                timed_out=True,
                error=f"timeout after {timeout_seconds}s",
                cost_usd=stats.cost,
                n_llm_calls=stats.n_calls,
                n_steps=stats.n_steps,
                transcript_path=str(transcript_path) if transcript_path else None,
                raw_responses_path=str(raw_responses_path) if raw_responses_path else None,
            )
        except Exception as e:
            logger.error("Agent error on %s: %s", instance_id, e)
            return AgentRunResult(
                instance_id=instance_id,
                model_patch="",
                error=str(e),
                cost_usd=stats.cost,
                n_llm_calls=stats.n_calls,
                n_steps=stats.n_steps,
                transcript_path=str(transcript_path) if transcript_path else None,
                raw_responses_path=str(raw_responses_path) if raw_responses_path else None,
            )

    patch = _git_diff(repo_dir)
    logger.debug("Agent finished %s: patch=%d chars, cost=$%.4f, calls=%d, steps=%d",
                 instance_id, len(patch), stats.cost, stats.n_calls, stats.n_steps)

    return AgentRunResult(
        instance_id=instance_id,
        model_patch=patch,
        cost_usd=stats.cost,
        n_llm_calls=stats.n_calls,
        n_steps=stats.n_steps,
        transcript_path=str(transcript_path) if transcript_path else None,
        raw_responses_path=str(raw_responses_path) if raw_responses_path else None,
    )
