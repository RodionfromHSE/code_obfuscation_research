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

# identity (no obfuscation) baseline, 3 instances
uv run python -m swebench_task samples_limit=3

# rope rename obfuscation, 16 agents in parallel
uv run python -m swebench_task repo_obfuscation=rope_rename samples_limit=16 agent.concurrency=16

# re-run the same config — cached instances return instantly, no API cost
uv run python -m swebench_task repo_obfuscation=rope_rename samples_limit=16

# alternative entrypoint
uv run python swebench_task/scripts/run.py repo_obfuscation=rope_rename samples_limit=3

# kill the docker bottleneck: prebuild images for the top-3 most-populous repo buckets
uv run python -m swebench_task.scripts.prebuild_images --top-k 3 --max-total-gb 40
uv run python -m swebench_task priority_instances=swebench_task/configs/priority_instances.yaml
```

See [docs/guides/prebuild_images.md](docs/guides/prebuild_images.md) for the full prebuild workflow.

All parameters are [Hydra](https://hydra.cc/) overrides on top of
[configs/default.yaml](configs/default.yaml).

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `model` | `gpt5_4_nano` | Model config group. Options: `gpt5_4_nano`, `gpt5_4_mini`, `gpt4o`, `claude_sonnet` |
| `repo_obfuscation` | `identity` | Obfuscation strategy. Options: `identity`, `rope_rename` |
| `dataset.name` | `SWE-bench/SWE-bench_Verified` | HuggingFace dataset |
| `dataset.split` | `test` | Dataset split |
| `dataset.shuffle_seed` | `42` | Seed for shuffling instances (ignored if `instance_order.yaml` exists) |
| `samples_limit` | `null` (all) | Cap number of instances |
| `experiment_name` | `swebench_identity` | Run output subdirectory name |
| `agent.model_name` | (set by model config) | Model passed to mini-swe-agent via litellm |
| `agent.max_turns` | `50` | Max agent interaction turns |
| `agent.cost_limit` | `3.0` | USD cost limit per instance |
| `agent.timeout_seconds` | `1200` | Per-instance wall-clock timeout |
| `agent.concurrency` | `1` | Concurrent agents via asyncio.Semaphore + to_thread. Bump to 8-16 for big runs |
| `cache.enabled` | `true` | Global cross-experiment cache keyed by (obfuscation, model, instance_id) |
| `cache.read_only` | `false` | If true, cache is read-only (useful for re-scoring without re-writing) |
| `eval.max_workers` | `4` | Docker eval parallelism. Lower to 2 for heavy envs (sklearn/astropy) |
| `eval.timeout` | `1800` | Per-instance Docker eval timeout in seconds |
| `clone.shallow` | `true` | Use `git clone --filter=blob:none` for 5-10x faster clones |

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
load_instances()  ──>  [SWEBenchInstance, ...]  (order from instance_order.yaml)
    |
    |  per instance (optionally concurrent):
    |    cache.get(obf, model, iid)  ──> hit? return. miss? ↓
    |    clone_repo()                 (--filter=blob:none)
    |    obfuscated_repo()            — temp copy + rope rename + git commit
    |    run_agent()                  — mini-swe-agent on obfuscated code
    |    git diff                     — agent-only changes
    |    deobfuscate_patch()          — reverse-map names back to originals
    |    cache.put(...)               — if non-infra outcome
    |
    v
save_predictions()  ──>  predictions.jsonl  (filtered to non-cached)
    |
    v
run_swebench_eval()  ──>  Docker: git apply patch, run tests (tqdm progress bar)
    |
    v
save_summary_report()  ──>  summary.json + per-instance reports
```

## Module structure

```
swebench_task/
├── __main__.py                  # `python -m swebench_task` entry point
├── __init__.py
├── AGENTS.md                    # agent reference (build, run, conventions)
├── README.md                    # this file
├── source/
│   ├── pipeline.py              # main orchestrator: cache, agent loop, eval
│   ├── dataset.py               # SWEBenchInstance dataclass + HF loader + git clone
│   ├── cache.py                 # RunCache + CacheKey + is_reusable
│   └── async_runner.py          # asyncio.Semaphore bounded agent pool
├── agent/
│   └── runner.py                # mini-swe-agent wrapper (timeout, cost tracking)
├── evaluation/
│   ├── swebench_eval.py         # Docker-based SWE-bench harness wrapper
│   ├── eval_progress.py         # tqdm-backed polling progress monitor
│   └── oom_audit.py             # env-image RAM heuristic audit script
├── obfuscation/
│   ├── protocol.py              # RepoObfuscation protocol + RepoObfuscationResult
│   ├── identity.py              # noop baseline
│   ├── rope_renamer.py          # cross-file symbol rename via rope (+ ignored_resources fix)
│   └── repo_copy.py             # temp-copy context manager + git commit
├── utils/
│   ├── logging_config.py        # dual logging (verbose file + clean stdout)
│   ├── litellm_setup.py         # register dated model slugs for cost tracking
│   └── reporting.py             # per-instance JSON + summary report generation
├── configs/
│   ├── default.yaml             # top-level Hydra config
│   ├── docker_skip.yaml         # 190 instances to skip (observed OOM + heuristic OOM)
│   ├── instance_order.yaml      # frozen shuffled order of 310 usable IDs
│   ├── paths/default.yaml       # artifact path resolution
│   ├── model/                   # model config group
│   └── repo_obfuscation/        # obfuscation config group
├── prebuild/                    # out-of-band top-K docker image prebuilder
│   ├── image_selection.py       # bucket grouping + top-K-under-budget (pure, unit-tested)
│   ├── manifest.py              # PrebuildManifest + cleanup.sh generator
│   ├── prebuilder.py            # wraps swebench.harness.prepare_images.main
│   └── priority_yaml.py         # read/write priority_instances.yaml
├── scripts/
│   ├── run.py                   # alternative Hydra CLI entry point
│   ├── freeze_instance_order.py # one-shot: regenerate instance_order.yaml
│   ├── prebuild_images.py       # top-K docker image prebuilder (see docs/guides/)
│   ├── cleanup_prebuilt_images.py  # rmi images listed in manifest
│   └── smoke_test.py            # end-to-end 3-instance smoke (cache + async + tqdm)
├── tests/
│   ├── test_obfuscation.py          # 26 unit tests
│   ├── test_image_selection.py      # 9 prebuild-selection tests
│   ├── test_prebuild_manifest.py    # 7 manifest round-trip tests
│   └── test_priority_filter.py      # 6 priority-filter tests
├── docs/
│   ├── README.md                # docs index
│   ├── reference/               # tutorial, architecture
│   ├── guides/                  # prebuild_images.md
│   ├── reports/                 # oom_audit, obfuscation_fixes, acceleration, run comparisons
│   └── dev/                     # devlog, pr_description
└── artifacts/                   # repos, runs, logs, cache (gitignored)
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
├── cache/                            # global cross-experiment results cache
│   └── <obfuscation>/<model>/<instance_id>.json
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

**Current implementations:**

- **identity** — noop baseline, passes code through unchanged
- **rope_rename** — renames up to 200 public functions/classes to `func_N`/`cls_N`
  across all files using rope's cross-file refactoring. Test dirs are excluded via
  rope's `ignored_resources` (fixes Django 4.0+ syntax-error issue). Deobfuscation
  is a single-pass regex word-boundary replacement using the rename map.

## How to extend

**New obfuscation:** implement the `RepoObfuscation` protocol, add a YAML in
`configs/repo_obfuscation/` with `_target_` pointing to your class. Run with
`repo_obfuscation=your_config_name`.

**Different model:** pick a config or override directly:
```bash
uv run python -m swebench_task model=gpt4o samples_limit=5
uv run python -m swebench_task agent.model_name=openai/gpt-4o-mini samples_limit=5
```

**Different dataset/split:**
```bash
uv run python -m swebench_task dataset.name=SWE-bench/SWE-bench_Lite dataset.split=test
```

## Tests

```bash
uv run pytest swebench_task/tests/ -v
uv run python swebench_task/scripts/smoke_test.py   # end-to-end 3-instance cache + async check
```

48 unit tests total: 26 for obfuscation (protocol conformance, rope rename correctness,
test-dir exclusion, syntax-error fallback, context manager lifecycle, deobfuscation
edge cases, full round-trip); 22 for the prebuild module (bucket grouping/ranking,
budget cap, manifest round-trip, cleanup script, priority filter). No API or Docker needed.

## Skip list

190 of 500 instances are skipped by default ([configs/docker_skip.yaml](configs/docker_skip.yaml)):

- **130 Docker OOM (observed)** — older Django (3.0-3.2) and Astropy envs that OOM
  (exit 137) with default Docker memory (~8 GB). Expanded from 57 observed failures
  to all instances sharing the same `environment_setup_commit`.
- **60 OOM-likely (heuristic)** — from
  [docs/reports/oom_audit.md](docs/reports/oom_audit.md): scikit-learn 0.20-1.3,
  xarray 0.12-2022.09, astropy 3.1-5.2, seaborn 0.12.

Remaining usable: **310 instances** across 12 repos. Order frozen in
[configs/instance_order.yaml](configs/instance_order.yaml) — adding to the skip
list only removes items, doesn't reshuffle.

## Further reading

- [docs/README.md](docs/README.md) — full documentation index
- [docs/reference/tutorial.md](docs/reference/tutorial.md) — step-by-step walkthrough (start here)
- [docs/reports/oom_audit.md](docs/reports/oom_audit.md) — why the skip list looks the way it does
- [docs/reports/obfuscation_fixes.md](docs/reports/obfuscation_fixes.md) — rope fix explained
- [docs/reports/acceleration.md](docs/reports/acceleration.md) — performance shipped + roadmap
