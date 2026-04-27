# AGENTS.md

## Project

SWE-bench obfuscation experiment: measure how code obfuscation degrades an LLM coding agent on real-world GitHub issues.

- Agent model: `gpt-5.4-nano-2026-03-17` (via litellm)
- Agent harness: `mini-swe-agent` v2.2.8
- Dataset: `SWE-bench/SWE-bench_Verified` (500 instances, 310 usable post-skip)
- Obfuscation: cross-file symbol rename via `rope` (tests/docs in `ignored_resources`)
- Evaluation: `swebench` Docker harness (git apply + test suite)

## Build & Test

```bash
uv sync --all-extras                                 # install deps
uv run pytest swebench_task/tests/ -v                # 26 unit tests (no API/Docker)
uv run python swebench_task/scripts/smoke_test.py    # 3-instance end-to-end (cache + async + tqdm)
uv run ruff check swebench_task/                     # lint
```

## Run

```bash
# identity baseline, 3 instances sequentially
uv run python -m swebench_task samples_limit=3

# rope rename, 16 parallel agents, mini model
uv run python -m swebench_task repo_obfuscation=rope_rename samples_limit=16 \
  agent.concurrency=16 model=gpt5_4_mini

# re-run — cached instances return instantly
uv run python -m swebench_task repo_obfuscation=rope_rename samples_limit=16

# full 310-instance run (requires Docker, ~$500+ in API costs)
uv run python -m swebench_task repo_obfuscation=rope_rename agent.concurrency=16
```

All parameters are Hydra overrides on [configs/default.yaml](configs/default.yaml).

## Maintenance scripts

```bash
# after editing docker_skip.yaml, regenerate the ordered list (seed=42)
uv run python -m swebench_task.scripts.freeze_instance_order

# re-audit env images (updates docs/reports/oom_audit.md and oom_audit_additions.yaml)
uv run python -m swebench_task.evaluation.oom_audit
```

## Code Style

- Python 3.12+; modern typing (`list[str]`, `X | None`, no `Optional`, no `from __future__`)
- Imports always at top of file
- Minimal comments/docstrings; prefer good names over commentary
- `uv add ...` for new dependencies
- One concern per file; keep pipeline.py < 250 lines

## Architecture

- `source/pipeline.py` -- orchestrator: load -> cache-check -> obfuscate -> agent -> eval -> report
- `source/dataset.py` -- `SWEBenchInstance`, HF loader, `load_instance_order`, partial clone
- `source/cache.py` -- `RunCache`/`CacheKey`; caches `resolved/failed/empty_patch/agent_timeout`
- `source/async_runner.py` -- asyncio.Semaphore bounded pool over sync `process_fn`
- `agent/runner.py` -- mini-swe-agent wrapper with ThreadPoolExecutor timeout + cost tracking
- `evaluation/swebench_eval.py` -- Docker harness wrapper, predictions JSONL writer
- `evaluation/eval_progress.py` -- tqdm-backed polling monitor
- `evaluation/oom_audit.py` -- one-shot RAM heuristic audit
- `obfuscation/` -- protocol, identity baseline, rope renamer (with `ignored_resources`), temp-copy ctx
- `utils/` -- logging, litellm cost registration, per-instance + summary JSON
- `configs/` -- Hydra groups: paths, repo_obfuscation, model + top-level (cache, agent, eval, clone)
- `scripts/` -- `run.py` (alt CLI), `freeze_instance_order.py`, `smoke_test.py`
- `tests/` -- 26 unit tests (protocol, rename, deobfuscation, round-trip)
- `docs/` -- `reference/`, `reports/`, `dev/` (see `docs/README.md` index)

## Conventions

- Obfuscation strategies implement `RepoObfuscation` protocol; pipeline doesn't know reversal details
- Obfuscation always works on a temp copy (`shutil.copytree`); original clone is never modified
- Rope's `ignored_resources` excludes tests/docs/examples (plus any AST-broken file) — this fixes Django 4.0+
- After obfuscation, `git commit` establishes baseline so `git diff` captures only agent changes
- Deobfuscation uses regex word-boundary replacement (not rope in reverse) — fast, no syntax needed
- Skip list (`configs/docker_skip.yaml`) auto-loaded; `configs/instance_order.yaml` freezes shuffle
- Cache (`artifacts/cache/`) is global; only caches non-infra statuses. Never caches eval_error
- `agent.concurrency > 1` uses asyncio + to_thread; rope's signal-based timeout no-ops in worker threads
- Third-party noise (litellm, mini-swe-agent, HuggingFace) suppressed via env vars + logger config

## How to extend

**New obfuscation**: implement `RepoObfuscation` protocol (`obfuscate()` + `deobfuscate_patch()`), add YAML in `configs/repo_obfuscation/` with `_target_` pointing to your class. Run with `repo_obfuscation=your_name`.

**New model**: add a YAML in `configs/model/` setting `agent.model_name` (litellm format) and cost/timeout defaults. Run with `model=your_name`. Or override directly: `agent.model_name=openai/gpt-4o-mini`.

**Different dataset/split**: override `dataset.name` and `dataset.split`. The loader expects SWE-bench schema (instance_id, repo, base_commit, problem_statement, patch, test_patch). Regenerate `instance_order.yaml` afterwards.
