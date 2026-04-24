# AGENTS.md

## Project

SWE-bench obfuscation experiment: measure how code obfuscation degrades an LLM coding agent on real-world GitHub issues.

- Agent model: `gpt-5.4-nano-2026-03-17` (via litellm)
- Agent harness: `mini-swe-agent` v2.2.8
- Dataset: `SWE-bench/SWE-bench_Verified` (500 instances, HuggingFace)
- Obfuscation: cross-file symbol rename via `rope`
- Evaluation: `swebench` Docker harness (git apply + test suite)

## Build & Test

```bash
uv sync --all-extras                      # install deps
uv run pytest swebench_task/tests/ -v     # 25 tests (no API/Docker needed)
uv run ruff check swebench_task/          # lint
```

## Run

```bash
# identity baseline, 3 instances
uv run python -m swebench_task samples_limit=3

# rope rename obfuscation
uv run python -m swebench_task repo_obfuscation=rope_rename samples_limit=3

# different model (via config group)
uv run python -m swebench_task model=gpt4o samples_limit=3
uv run python -m swebench_task model=claude_sonnet samples_limit=3

# full 500 instances (requires Docker, ~$500+ in API costs)
uv run python -m swebench_task repo_obfuscation=rope_rename
```

All parameters are Hydra overrides on [configs/default.yaml](configs/default.yaml).

## Code Style

- Python 3.12+; modern typing (`list[str]`, `X | None`, no `Optional`, no `from __future__`)
- Imports always at top of file
- Minimal comments/docstrings; prefer good names over commentary
- `uv add ...` for new dependencies

## Architecture

- `pipeline.py` -- main orchestrator: load → obfuscate → agent → deobfuscate → eval → report
- `dataset.py` -- `SWEBenchInstance` dataclass, HuggingFace loader, git clone
- `agent/` -- mini-swe-agent wrapper with ThreadPoolExecutor timeout and cost tracking
- `evaluation/` -- Docker-based SWE-bench harness wrapper, predictions JSONL writer
- `obfuscation/` -- `RepoObfuscation` protocol, identity baseline, rope renamer, temp-copy context manager
- `utils/` -- dual logging (verbose file + clean stdout), per-instance + summary JSON reporting
- `configs/` -- Hydra config groups (paths, repo_obfuscation, dataset, agent)
- `scripts/` -- alternative CLI entry point (`run.py`)
- `tests/` -- 25 unit tests (protocol, rename, deobfuscation, round-trip)
- `docs/` -- architecture, devlog, experiment reports

## Conventions

- Obfuscation strategies implement `RepoObfuscation` protocol; pipeline never knows reversal details
- Obfuscation always works on a temp copy (`shutil.copytree`); original clone is never modified
- After obfuscation, `git commit` establishes baseline so `git diff` captures only agent changes
- Deobfuscation uses regex word-boundary replacement (not rope in reverse) -- fast, no syntax needed
- Docker skip list (`configs/docker_skip.yaml`) auto-loaded; 57 instances excluded (OOM on default Docker memory)
- Third-party noise (litellm, mini-swe-agent, HuggingFace) suppressed via env vars + logger config + stderr redirect
- Artifacts go to `swebench_task/artifacts/` (repos cached across runs)

## How to extend

**New obfuscation**: implement `RepoObfuscation` protocol (`obfuscate()` + `deobfuscate_patch()`), add YAML in `configs/repo_obfuscation/` with `_target_` pointing to your class. Run with `repo_obfuscation=your_name`.

**New model**: add a YAML in `configs/model/` setting `agent.model_name` (litellm format) and cost/timeout defaults. Run with `model=your_name`. Or override directly: `agent.model_name=openai/gpt-4o-mini`.

**Different dataset/split**: override `dataset.name` and `dataset.split`. The loader expects SWE-bench schema (instance_id, repo, base_commit, problem_statement, patch, test_patch).
