# Code Obfuscation Research

Measure how much utility drops when code is perturbated (obfuscated) before being sent to an LLM for privacy protection.

## Architecture

```
HuggingFace dataset
    -> DatasetAdapter (normalizes rows into CodeTaskSample)
    -> Perturbation (rewrites CodeArtifact, e.g. rename symbols)
    -> TaskDefinition (builds prompt from sample + perturbed code)
    -> LLMRuntime (async, cached, with parse-aware retry)
    -> RunRecord JSONL (one file per experiment+perturbation)
    -> EvalPipeline (reads JSONL, never calls the task model again)
    -> DeepEval binary correctness (judge sees question + answer only, not code)
    -> CorrectnessResult JSONL
```

See local READMEs for details:
- [domain/](src/code_obfuscation_research/domain/README.md) -- entities, protocols, contracts
- [tasks/](src/code_obfuscation_research/tasks/README.md) -- prompt templates, expected outputs
- [perturbations/](src/code_obfuscation_research/perturbations/README.md) -- what transforms do
- [runtime/](src/code_obfuscation_research/runtime/README.md) -- cache, retry, concurrency
- [evaluation/](src/code_obfuscation_research/evaluation/README.md) -- how correctness is judged

## Quick start

```bash
uv sync --all-extras
uv run pytest                                                   # tests
uv run python scripts/run_experiment.py samples_limit=3         # 3-sample smoke run
uv run python scripts/run_experiment.py perturbation=rename_symbols samples_limit=3
uv run python scripts/run_evaluation.py samples_limit=3         # evaluate saved runs
```

## Overrides

Both scripts use Hydra. Override any config value from the CLI:

```bash
uv run python scripts/run_experiment.py \
    model=openai_gpt5_4_nano \
    perturbation=rename_symbols \
    samples_limit=100 \
    experiment_name=rename_100
```

## Artifacts

Run outputs go to `artifacts/runs/{experiment}_{perturbation}.jsonl` -- one `RunRecord` per line with sample_id, request messages, model response, reference answer, and perturbation stats.

Eval outputs go to `artifacts/evals/{experiment}_results.jsonl` -- one `CorrectnessResult` per line with sample_id, perturbation_name, is_correct (0/1), and judge reasoning.

Both directories are gitignored.

## Structure

```
src/code_obfuscation_research/
  domain/         immutable entities + protocols
  tasks/          task definitions (codeqa, ...)
  datasets/       HuggingFace adapters
  perturbations/  code-first transforms (noop, rename_symbols)
  models/         LangChain OpenAI adapter
  runtime/        cache, LLM runtime, JSONL store
  evaluation/     binary correctness via DeepEval
  pipelines/      run + eval orchestration
scripts/          Hydra entry points
configs/          Hydra config groups
tests/            unit + integration tests
artifacts/        cache, runs, evals (gitignored)
```
