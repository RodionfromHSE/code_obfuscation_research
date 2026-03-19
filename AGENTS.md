# AGENTS.md

## Project

Code privacy benchmark: perturb Python code before sending to LLM, measure utility drop.

- Task model: `gpt-5.4-nano-2026-03-17`
- Judge model: `gpt-5.4-mini-2026-03-17`
- Dataset: `vm2825/CodeQA-dataset` (HuggingFace)

## Build & Test

```bash
uv sync --all-extras          # install deps
uv run pytest                  # all tests
uv run ruff check src/ tests/  # lint
```

## Run

```bash
uv run python scripts/run_experiment.py samples_limit=3                     # noop baseline
uv run python scripts/run_experiment.py perturbation=rename_symbols samples_limit=3  # perturbed
uv run python scripts/run_evaluation.py samples_limit=3                     # evaluate
```

## Code Style

- Python 3.12+; modern typing (`list[str]`, `X | None`, no `Optional`, no `from __future__`)
- Imports always at top of file
- Minimal comments/docstrings; prefer good names over commentary
- `boilerplate_tools.setup_root(n_up=1)` only in `scripts/` entry points
- `uv add ...` for new dependencies

## Architecture

- `domain/` -- immutable entities and protocols ([README](src/code_obfuscation_research/domain/README.md))
- `tasks/` -- prompt templates, response parsing, eval case building ([README](src/code_obfuscation_research/tasks/README.md))
- `datasets/` -- HuggingFace adapters; normalize rows into domain samples immediately
- `perturbations/` -- code-first transforms; never touch prompts or models ([README](src/code_obfuscation_research/perturbations/README.md))
- `models/` -- thin LangChain/OpenAI adapters with full parameter support
- `runtime/` -- shared async/cache/retry runtime + JSONL store ([README](src/code_obfuscation_research/runtime/README.md))
- `evaluation/` -- DeepEval binary correctness (GEval strict_mode) ([README](src/code_obfuscation_research/evaluation/README.md))
- `pipelines/` -- orchestration (run_pipeline + eval_pipeline)
- `configs/` -- Hydra config groups (paths, task, dataset, model, judge_model, runtime, perturbation, evaluator)
- `scripts/` -- CLI entry points

## Runtime features

- Persistent SQLite cache via `InvalidatableSQLiteCache` (path from Hydra config)
- Parse-aware cache invalidation: on parse failure, cached entries from that call are deleted so the retry gets a fresh API response
- Async concurrency bounded by `asyncio.Semaphore(max_concurrent)` inside `LLMRuntime`
- Pydantic structured output parsing via `invoke_structured()` with retry loop

## Conventions

- Never couple perturbations to dataset-specific schemas
- Smoke tests use `limit=3` and request timeouts
- Evaluation reads saved run artifacts; never calls the task model again
- Cache and output paths come from Hydra configs, never hardcoded
- Perturbations accept `PerturbationInput` (code + optional metadata), return `PerturbationResult`
- All model interaction goes through `LLMRuntime`; no direct LangChain calls outside `runtime/`

## How to extend

**New dataset**: implement `DatasetAdapter` protocol, return `list[CodeTaskSample]` (or subclass), add yaml in `configs/dataset/`.

**New task**: implement `TaskDefinition` protocol (build_request, parse_prediction, build_reference, build_eval_case), add yaml in `configs/task/`.

**New perturbation**: implement `Perturbation` protocol (`apply(PerturbationInput) -> PerturbationResult`), add yaml in `configs/perturbation/`. Work only with `CodeArtifact`, never depend on sample type.
