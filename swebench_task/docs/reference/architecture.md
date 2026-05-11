# SWE-bench Obfuscation Pipeline: Architecture

## Goal

Measure how code obfuscation degrades an LLM-based coding agent's ability to solve
real-world software engineering tasks. We use SWE-bench Verified as the benchmark,
mini-swe-agent as the agent harness, and rope for cross-file symbol renaming.

## High-level data flow

```
SWE-bench dataset
      |
      v
  load_instances() ──> [SWEBenchInstance, ...]
      |
      ╔═══════════════ per instance ═══════════════╗
      ║  clone_repo()                               ║
      ║       |                                     ║
      ║       v                                     ║
      ║  obfuscated_repo() context manager          ║
      ║    1. shutil.copytree (temp copy)           ║
      ║    2. obfuscation.obfuscate()               ║
      ║    3. git add + commit (baseline)           ║
      ║       |                                     ║
      ║       v                                     ║
      ║  run_agent() on obfuscated copy             ║
      ║       |                                     ║
      ║       v                                     ║
      ║  git diff (agent-only changes)              ║
      ║       |                                     ║
      ║       v                                     ║
      ║  obfuscation.deobfuscate_patch()            ║
      ║    reverse-map obfuscated names → originals ║
      ║       |                                     ║
      ║       v                                     ║
      ║  clean patch (original names)               ║
      ╚════════════════════════════════════════════╝
      |
      v
  save_predictions() ──> predictions.jsonl
      |
      v
  run_swebench_eval() (Docker)
      |
      v
  save_summary_report() ──> summary.json
```

## Module structure

```
swebench_task/
├── __main__.py              # python -m swebench_task entry point
├── pipeline.py              # main orchestrator (run_swebench_pipeline)
├── dataset.py               # SWEBenchInstance dataclass, HuggingFace loader, git clone
├── agent/
│   └── runner.py            # mini-swe-agent wrapper with timeout/cost tracking
├── evaluation/
│   └── swebench_eval.py     # Docker-based SWE-bench test harness
├── obfuscation/
│   ├── protocol.py          # RepoObfuscation protocol + RepoObfuscationResult
│   ├── identity.py          # noop baseline
│   ├── rope_renamer.py      # cross-file symbol rename via rope
│   └── repo_copy.py         # temp-copy context manager + git commit
├── utils/
│   ├── logging_config.py    # dual logging (verbose file + clean stdout)
│   └── reporting.py         # per-instance JSON + summary report generation
├── configs/
│   ├── default.yaml         # top-level Hydra config
│   ├── docker_skip.yaml     # instances to skip (Docker OOM)
│   ├── paths/default.yaml   # artifact path resolution
│   └── repo_obfuscation/
│       ├── identity.yaml
│       └── rope_rename.yaml
├── scripts/
│   └── run.py               # alternative Hydra CLI entry point
├── tests/
│   └── test_obfuscation.py  # 25 unit tests
└── docs/                    # this file, devlog, experiment reports
```

## Key design decisions

### Reversible obfuscation protocol

Every obfuscation implements two methods:

```python
class RepoObfuscation(Protocol):
    name: str
    def obfuscate(self, repo_dir: Path) -> RepoObfuscationResult: ...
    def deobfuscate_patch(self, patch: str, result: RepoObfuscationResult) -> str: ...
```

The agent works on obfuscated code and produces patches with obfuscated names.
`deobfuscate_patch` reverses those names so the patch can be applied to the original repo
for evaluation. Each obfuscation owns its reversal logic — the pipeline doesn't know how
the reversal works, it just calls the protocol method.

This is necessary because SWE-bench eval applies `git apply <patch>` to the original
(non-obfuscated) repo and runs the test suite. A patch containing `func_0` where the
original code has `compute` would fail to apply.

### Why git commit before agent runs

After obfuscation, we `git add -A && git commit`. This establishes the obfuscated state
as the baseline so `git diff` after the agent runs captures only the agent's changes,
not the obfuscation itself. Without this, the 200-symbol rename across 174 files would
appear as a 700K-char diff attributed to the agent.

### Deobfuscation via regex, not rope

We use `\b(cls_0|cls_10|func_0|...)\b` word-boundary regex replacement instead of
running rope in reverse because:

- Rope is slow (~60s for 200 symbols on astropy) and the agent may have broken syntax
- The generated names (`func_N`, `cls_N`) are guaranteed unique — no collision possible
- Word boundaries handle edge cases: `func_0_extra` is not replaced, `computed_result`
  survives when `compute` -> `func_0`
- It's a pure string function — trivially testable without filesystem

### Temporary copies for isolation

`obfuscated_repo()` creates a fresh `shutil.copytree` for each instance, runs
obfuscation in-place on the copy, and auto-cleans via `tempfile.TemporaryDirectory`.
The original cloned repo is never modified, so identity and rename runs share cached
clones.

### Logging: suppressing third-party noise

litellm, mini-swe-agent, and HuggingFace all produce verbose stdout/stderr output.
We suppress it at three levels:

1. **Environment variables** set before imports: `MSWEA_SILENT_STARTUP`, `LITELLM_LOG=ERROR`
2. **Logger configuration**: all third-party loggers set to ERROR, pre-attached StreamHandlers removed
3. **stderr redirect**: `os.dup2` redirects fd 2 to the log file to catch raw `print()` calls
   (litellm's "Provider List" spam uses `print()`, not logging)

### Docker skip list

57 SWE-bench instances consistently fail with exit code 137 (OOM) when Docker Desktop
has default memory limits. These are older Django and Astropy environments that compile
numpy/scipy from source inside the container. Listed in `configs/docker_skip.yaml`, loaded
automatically by `load_instances()`.

## Configuration (Hydra)

Obfuscation is swappable via command line:
```bash
uv run python -m swebench_task repo_obfuscation=identity     # baseline
uv run python -m swebench_task repo_obfuscation=rope_rename   # obfuscated
```

All parameters (model, max_turns, cost_limit, timeout, samples_limit) are configurable
via Hydra overrides. Adding a new obfuscation: implement the protocol, add a YAML config
in `configs/repo_obfuscation/`.

## Agent integration

`agent/runner.py` wraps mini-swe-agent's `DefaultAgent` with:
- `ThreadPoolExecutor`-based timeout (configurable, default 1200s)
- Cost and step tracking extracted from `agent.cost`, `agent.n_calls`, `agent.messages`
- litellm cost errors suppressed via `MSWEA_COST_TRACKING=ignore_errors` (gpt-5.4-nano
  is not in litellm's price registry)

## Evaluation

`evaluation/swebench_eval.py` calls `swebench.harness.run_evaluation` which:
1. Builds Docker images for each instance's environment
2. Applies the agent's patch via `git apply`
3. Runs the test suite
4. Writes per-instance `report.json` files under `logs/run_evaluation/<run_id>/`

We parse these reports and merge in `error_ids` from the global summary (Docker build
failures) to produce `SWEBenchEvalResult` for each instance.

## Test strategy

25 tests, all unit-level (no API calls, no Docker):

- **Protocol conformance**: `isinstance(X, RepoObfuscation)` for each implementation
- **Obfuscation correctness**: rope renames functions/classes across files, updates imports,
  skips private names, skips test file definitions, updates test file references
- **Context manager**: creates temp copy, cleans up, original untouched
- **Deobfuscation unit tests**: basic reverse, empty patch, no rename_map, longest-first
  ordering, word boundary, substring safety, string literals, comments, agent-created variables,
  multiple names on same line, diff context lines
- **Round-trip integration**: obfuscate → edit → git diff → deobfuscate → `git apply` to
  original → verify file content (3 variants: rename, rename with substring var, identity)
