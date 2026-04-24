# PR: standalone SWE-bench obfuscation experiment module

## Summary

Moves all SWE-bench experiment code from `src/swe_task/` into a self-contained
`swebench_task/` package at the project root. The package owns its configs,
scripts, tests, documentation, and runtime artifacts.

## What changed

### Structure

- **Deleted** `src/swe_task/`, `configs/swebench/`, `configs/repo_obfuscation/`,
  `scripts/run_swebench.py`, `tests/unit/swe_task/`, `docs/swe_task_impl/`.
- **Created** `swebench_task/` with subpackages: `source/` (pipeline + dataset),
  `agent/`, `evaluation/`, `obfuscation/`, `utils/`, `configs/`, `scripts/`,
  `tests/`, `docs/`.

### Core logic (in `source/`)

- `dataset.py` — loads SWE-bench Verified from HuggingFace, applies a seeded
  shuffle (default seed=42) before slicing by `samples_limit` so that subsets
  have diverse repo coverage instead of being biased by HF's repo-grouped order.
- `pipeline.py` — orchestrates: load instances, clone repos, obfuscate, run
  agent, deobfuscate patch, evaluate via Docker, save reports.

### Configuration

- Hydra config groups: `model/` (gpt5_4_nano, gpt5_4_mini, gpt4o,
  claude_sonnet), `repo_obfuscation/` (identity, rope_rename), `paths/`.
- `docker_skip.yaml` — **237 / 500 instances** skipped, leaving 263 usable.
  Built by systematically checking all 500 instances (not just from runs):
  - 107 Django 4.0+ instances where an intentional syntax error file poisons
    rope's project-wide parse.
  - 130 older Django/Astropy instances sharing `environment_setup_commit` with
    observed Docker OOM failures.

### Utilities

- `litellm_setup.py` — registers dated model slugs (e.g. `gpt-5.4-nano-2026-03-17`)
  in litellm's cost map so cost tracking works out of the box.
- `logging_config.py` — dual logging: verbose to file, clean to stdout.
- `reporting.py` — per-instance JSON reports + aggregate summary.

### Entry points

```bash
# primary
uv run python -m swebench_task model=gpt5_4_mini repo_obfuscation=identity samples_limit=100

# alternative script
uv run python swebench_task/scripts/run.py model=gpt5_4_mini repo_obfuscation=rope_rename samples_limit=100
```

### Tests

25 unit tests (protocol conformance, rope rename, deobfuscation edge cases,
round-trip integration). No API calls or Docker needed:

```bash
uv run pytest swebench_task/tests/ -v
```

## Motivation

The original `src/swe_task/` was interleaved with the main research codebase,
sharing configs and artifact directories. Isolating it makes the experiment
reproducible, portable, and easier to extend with new obfuscation strategies
or models.
