# SWE-bench Obfuscation Experiment

Measures how code obfuscation degrades an LLM coding agent's ability to solve real-world
software engineering tasks. Uses [SWE-bench Verified](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified)
(500 GitHub issues from Django, Astropy, scikit-learn, etc.), [mini-swe-agent](https://mini-swe-agent.com)
as the agent harness, and [rope](https://github.com/python-rope/rope) for cross-file symbol renaming.

## Quick start

**Prerequisites:** Docker running (for SWE-bench eval), `OPENAI_API_KEY` set.

```bash
# from project root
uv sync --all-extras

# run with identity (no obfuscation) baseline, 3 instances
uv run python -m swebench_task samples_limit=3

# run with rope rename obfuscation
uv run python -m swebench_task repo_obfuscation=rope_rename samples_limit=3

# alternative: run via script
uv run python swebench_task/scripts/run.py repo_obfuscation=rope_rename samples_limit=3
```

All parameters are [Hydra](https://hydra.cc/) overrides on top of
[configs/default.yaml](configs/default.yaml).

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `model` | `gpt5_4_nano` | Model config group. Options: `gpt5_4_nano`, `gpt5_4_mini`, `gpt4o`, `claude_sonnet` |
| `repo_obfuscation` | `identity` | Obfuscation strategy. Options: `identity`, `rope_rename` |
| `dataset.name` | `SWE-bench/SWE-bench_Verified` | HuggingFace dataset |
| `dataset.split` | `test` | Dataset split |
| `dataset.shuffle_seed` | `42` | Seed for shuffling instances (`null` to disable) |
| `agent.model_name` | (set by model config) | Model passed to mini-swe-agent via litellm |
| `agent.max_turns` | `50` | Max agent interaction turns |
| `agent.cost_limit` | `3.0` | USD cost limit per instance |
| `agent.timeout_seconds` | `1200` | Per-instance wall-clock timeout |
| `samples_limit` | `null` (all) | Cap number of instances |
| `experiment_name` | `swebench_identity` | Run output subdirectory name |

Model configs live in [configs/model/](configs/model/) and set `agent.model_name` plus
sensible defaults for `cost_limit`. Add a new YAML to use any litellm-supported model.

Obfuscation configs live in [configs/repo_obfuscation/](configs/repo_obfuscation/).
Each YAML points to a Python class via Hydra's `_target_` and exposes its constructor
parameters (e.g. `max_symbols`, `per_symbol_timeout` for rope rename).

## Pipeline

```
SWE-bench Verified (HuggingFace)
    |
    v
load_instances()  ──>  [SWEBenchInstance, ...]
    |
    |  per instance:
    |    clone_repo()
    |    obfuscated_repo()  — temp copy + obfuscate in-place + git commit
    |    run_agent()        — mini-swe-agent on obfuscated code
    |    git diff           — agent-only changes
    |    deobfuscate_patch()— reverse-map names back to originals
    |
    v
save_predictions()  ──>  predictions.jsonl
    |
    v
run_swebench_eval()  ──>  Docker: git apply patch, run tests
    |
    v
save_summary_report()  ──>  summary.json + per-instance reports
```

The deobfuscation step is necessary because SWE-bench eval applies `git apply <patch>`
to the original (non-obfuscated) repo. A patch containing `func_0` where the original
code has `compute` would fail to apply.

## Module structure

```
swebench_task/
├── __main__.py              # `python -m swebench_task` entry point
├── __init__.py
├── source/
│   ├── pipeline.py          # main orchestrator (run_swebench_pipeline)
│   └── dataset.py           # SWEBenchInstance dataclass + HF loader + git clone
├── agent/
│   └── runner.py            # mini-swe-agent wrapper (timeout, cost tracking)
├── evaluation/
│   └── swebench_eval.py     # Docker-based SWE-bench harness wrapper
├── obfuscation/
│   ├── protocol.py          # RepoObfuscation protocol + RepoObfuscationResult
│   ├── identity.py          # noop baseline
│   ├── rope_renamer.py      # cross-file symbol rename via rope
│   └── repo_copy.py         # temp-copy context manager + git commit
├── utils/
│   ├── logging_config.py    # dual logging (verbose file + clean stdout)
│   ├── litellm_setup.py     # register dated model slugs for cost tracking
│   └── reporting.py         # per-instance JSON + summary report generation
├── configs/
│   ├── default.yaml         # top-level Hydra config
│   ├── docker_skip.yaml     # 237 instances to skip (syntax error + Docker OOM)
│   ├── paths/default.yaml   # artifact path resolution
│   ├── model/               # model config group (gpt5_4_nano, gpt5_4_mini, ...)
│   └── repo_obfuscation/
│       ├── identity.yaml
│       └── rope_rename.yaml
├── scripts/
│   └── run.py               # alternative Hydra CLI entry point
├── tests/
│   └── test_obfuscation.py  # 25 unit tests
├── docs/                    # detailed design docs, experiment reports
└── artifacts/               # repos, runs, logs (generated at runtime, gitignored)
```

## Outputs

After a run, `swebench_task/artifacts/` contains:

```
artifacts/
├── repos/                            # cloned repos (cached across runs)
│   └── django__django-16527/
├── runs/<experiment_name>/
│   ├── predictions.jsonl             # SWE-bench format predictions
│   ├── summary.json                  # aggregate stats
│   └── instance_reports/
│       └── django__django-16527.json # per-instance detail
└── logs/
    └── <experiment_name>.log         # verbose debug log
```

## Obfuscation protocol

Every obfuscation strategy implements:

```python
class RepoObfuscation(Protocol):
    name: str
    def obfuscate(self, repo_dir: Path) -> RepoObfuscationResult: ...
    def deobfuscate_patch(self, patch: str, result: RepoObfuscationResult) -> str: ...
```

`obfuscate()` transforms the repo in-place (on a temp copy). `deobfuscate_patch()` reverses
obfuscated names in the agent's git diff so the patch applies cleanly to the original repo.

**Current implementations:**

- **identity** — noop baseline, passes code through unchanged
- **rope_rename** — renames up to 200 public functions/classes to `func_N`/`cls_N` across
  all files using rope's cross-file refactoring. Deobfuscation is a single-pass regex
  replacement using the rename map

## How to extend

**New obfuscation:** implement the `RepoObfuscation` protocol, add a YAML in
`configs/repo_obfuscation/` with `_target_` pointing to your class. Run with
`repo_obfuscation=your_config_name`.

**Different model:** pick a config or override directly:
```bash
uv run python -m swebench_task model=gpt4o samples_limit=5
uv run python -m swebench_task model=claude_sonnet samples_limit=5
# or any litellm model directly:
uv run python -m swebench_task agent.model_name=openai/gpt-4o-mini samples_limit=5
```

**Different dataset/split:**
```bash
uv run python -m swebench_task dataset.name=SWE-bench/SWE-bench_Lite dataset.split=test
```

## Tests

```bash
uv run pytest swebench_task/tests/ -v
```

25 unit tests covering protocol conformance, rope rename correctness, context manager
lifecycle, deobfuscation edge cases, and full round-trip integration (obfuscate, edit,
deobfuscate, `git apply`). No API calls or Docker needed.

## Skip list

237 of 500 instances are skipped by default ([configs/docker_skip.yaml](configs/docker_skip.yaml)):

- **107 rope syntax errors** — Django 4.0+ repos contain an intentional `tests_syntax_error.py`
  that poisons rope's project-wide parse, causing 0/200 renames. Detected by checking every
  Django `base_commit` in SWE-bench Verified against GitHub.
- **130 Docker OOM** — older Django (3.0-3.2) and Astropy envs that OOM (exit 137)
  with default Docker memory. Expanded from 57 observed failures to all instances
  sharing the same `environment_setup_commit` (same Docker image = same OOM).

Remaining usable: **263 instances** across 12 repos (75 sympy, 44 sphinx,
34 matplotlib, 32 sklearn, 22 xarray, 19 pytest, 12 django, 10 pylint,
8 requests, 4 astropy, 2 seaborn, 1 flask).

## Further reading

- [docs/tutorial.md](docs/tutorial.md) — step-by-step walkthrough of the full pipeline (start here)
- [docs/architecture.md](docs/architecture.md) — design decisions, deobfuscation strategy, logging approach
- [docs/identity_vs_rename_100.md](docs/identity_vs_rename_100.md) — 100-instance comparison: identity vs. rope rename
- [docs/devlog.md](docs/devlog.md) — chronological build log with problems encountered and fixes
- [docs/deobfuscation_e2e_report.md](docs/deobfuscation_e2e_report.md) — end-to-end verification of the deobfuscation protocol
