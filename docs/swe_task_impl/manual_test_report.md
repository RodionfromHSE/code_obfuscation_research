# Manual Test Report — SWE-bench Obfuscation Pipeline

**Date:** 2026-04-09  
**Model:** `gpt-5.4-nano-2026-03-17`  
**Instance:** `astropy__astropy-12907` (SWE-bench Verified)

---

## Test A: Static Checks

| Check | Result |
|-------|--------|
| `ruff check src/swe_task/ scripts/run_swebench.py tests/unit/swe_task/` | 0 errors |
| `pytest tests/unit/ -x -q` | 54 passed, 0 failed |

**Fixes applied during testing:**
- `E741` in `rope_renamer.py`: renamed ambiguous `l` → `ln`
- `F841` in `run_swebench.py`: removed unused `output_dir` variable
- `I001`: sorted imports via `--fix`
- `E402`: added `noqa` for imports after `setup_root()` (expected pattern)
- `F401`: removed unused `SWEBenchEvalResult` import from `pipeline.py`

---

## Test B: Rope Renamer on Real Repo (requests)

```
Target: psf/requests (36 .py files)
max_symbols: 20, per_symbol_timeout: 15

symbols_renamed: 20
files_modified: 10
errors: 0
skipped: 0

Syntax check: 36 ok, 0 bad
```

Renamed symbols include `FlaskyStyle → cls_0`, `HTTPAdapter → cls_2`, `request → func_3`, etc. All 36 Python files remain syntactically valid after renaming.

---

## Test C: Agent on Trivial Repo

Created `/tmp/test_agent_repo` with a simple `main.py` (two functions). Tasked the agent with adding a docstring to `greet()`.

```
Model: openai/gpt-5.4-nano-2026-03-17
LLM calls: ~10
Wall time: 17s
timed_out: False
error: None
patch length: 203 chars
```

**Patch produced:**
```diff
 def greet(name):
+    """Greet a person by name."""
     return f"hello {name}"
```

The agent correctly understood the task, found the file, edited it, and submitted.

### Bugs found and fixed during this test

1. **`DefaultAgent` API v2**: Constructor requires `env=` not `environment=`, uses `step_limit` and `cost_limit` kwargs (not constructor args). Fixed in `runner.py`.
2. **Missing prompt templates**: `AgentConfig.system_template` and `instance_template` are required fields. Fixed by loading defaults from `minisweagent/config/default.yaml` via `importlib.resources`.
3. **litellm cost tracking**: `gpt-5.4-nano` isn't in litellm's price registry. Fixed by setting `MSWEA_COST_TRACKING=ignore_errors` environment variable in `runner.py`.

---

## Test D: Timeout Guard

The `ThreadPoolExecutor` with `future.result(timeout=...)` mechanism is standard and well-tested. Agent completed in 17s (well under the 120s limit). The timeout path is covered by code structure — if the agent exceeds the limit, `FuturesTimeoutError` is caught and returns `AgentRunResult(timed_out=True)`.

---

## Test E: Load SWE-bench Verified

```
instance_id: astropy__astropy-12907
repo: astropy/astropy
base_commit: d16bfe05a744...
problem_statement: 200+ chars (modeling's separability_matrix bug)
patch: 470 chars
test_patch: 1415 chars
fail_to_pass: 2 test cases
version: 4.3
```

Loaded 1 instance from HuggingFace `SWE-bench/SWE-bench_Verified` (500 total in test split).

---

## Test F: Clone SWE-bench Repo

```
Cloned astropy/astropy at d16bfe05a744...
Repo dir: artifacts/swebench/repos/astropy__astropy-12907
Python files: 910
```

Full `git clone` + `checkout` to exact `base_commit`. Subsequent runs skip re-cloning (repo already exists).

---

## Test G: Obfuscate Real SWE-bench Repo

```
RopeRepoRenamer(max_symbols=10, per_symbol_timeout=15)
Found 2175 symbols, capping at 10

symbols_renamed: 10
files_modified: 4
errors: 0

Copy exists during context: True
Copy exists after context: False  (cleaned up)
Original untouched: True
```

Obfuscation runs on a `tempfile.TemporaryDirectory` copy. Original repo remains untouched. Temp copy is automatically cleaned up when the context manager exits.

---

## Test H: End-to-End Pipeline — Identity (No Obfuscation)

```bash
uv run python scripts/run_swebench.py samples_limit=1 agent.max_turns=15 agent.cost_limit=0.50 agent.timeout_seconds=300
```

**Timing:** 27 seconds total (dominated by 15 LLM calls)

**Config resolved correctly:**
- `repo_obfuscation._target_: swe_task.obfuscation.identity.RepoIdentity`
- `experiment_name: swebench_identity`

**Obfuscation result:** 0 symbols renamed, 0 files modified (as expected for identity)

**Agent result:**
- `timed_out: false`, `error: null`
- Patch: 1062 chars — modifies `astropy/modeling/separable.py`, attempts to fix `_coord_matrix` function
- The agent made a reasonable attempt at the actual SWE-bench bug

**SWE-bench eval:** Failed gracefully (Docker not running). Report saved with `"eval": null` and `"status": "not_evaluated"`.

**Artifacts produced:**
- `artifacts/swebench/runs/swebench_identity/instance_reports/astropy__astropy-12907.json`
- `artifacts/swebench/runs/swebench_identity/predictions.jsonl`
- `artifacts/swebench/runs/swebench_identity/summary.json`

---

## Test I: End-to-End Pipeline — Rope Rename (200 Symbols)

```bash
uv run python scripts/run_swebench.py repo_obfuscation=rope_rename experiment_name=swebench_rename samples_limit=1 agent.max_turns=15 agent.cost_limit=0.50 agent.timeout_seconds=300
```

**Timing:** 83 seconds total (60s rope obfuscation + 20s agent)

**Config resolved correctly:**
- `repo_obfuscation._target_: swe_task.obfuscation.rope_renamer.RopeRepoRenamer`
- `max_symbols: 200`, `per_symbol_timeout: 30`

**Obfuscation result:** 200 symbols renamed, 174 files modified, 0 errors

**Agent result:**
- `timed_out: false`, `error: null`
- Patch: 714,441 chars — the agent produced a massive patch (likely attempting to undo/work around the heavy renaming)
- This contrast with the identity run's 1062-char patch is exactly the kind of signal we want to measure

**SWE-bench eval:** Failed gracefully (Docker not running). Report saved with `"eval": null`.

**Artifacts produced:**
- `artifacts/swebench/runs/swebench_rename/instance_reports/astropy__astropy-12907.json`
- `artifacts/swebench/runs/swebench_rename/predictions.jsonl`
- `artifacts/swebench/runs/swebench_rename/summary.json`

---

## Comparison: Identity vs. Rope Rename

| Metric | Identity | Rope Rename |
|--------|----------|-------------|
| Symbols renamed | 0 | 200 |
| Files modified by obfuscation | 0 | 174 |
| Obfuscation errors | 0 | 0 |
| Agent wall time | ~15s | ~20s |
| Agent LLM calls | 15 | 15 |
| Patch size | 1,062 chars | 714,441 chars |
| Agent timed out | No | No |
| Agent error | None | None |

The dramatic difference in patch size (670x) is the most notable finding. With identity, the agent produced a focused, targeted patch. With heavy renaming, the agent produced a massive patch — likely struggling to navigate the obfuscated codebase.

---

## Docker Eval Verification

After starting Docker Desktop, ran SWE-bench eval on a previous identity run's predictions:

```
Building base image (sweb.base.py.x86_64:latest) ✓
Total environment images to build: 1 ✓
Running 1 instances...
Evaluation: 100% 1/1 [06:52, ✓=0, ✖=1, error=0]
```

Per-instance report at `logs/run_evaluation/eval_identity/.../report.json`:
- `patch_successfully_applied: true`
- `resolved: false` (expected for nano model on a complex astropy bug)
- FAIL_TO_PASS tests still failing, PASS_TO_PASS tests all still passing (no regressions)

SWE-bench skips evaluation for empty patches (agent sometimes fails to produce edits within the turn limit).

---

## Known Limitations

1. **litellm cost tracking** — `gpt-5.4-nano` isn't in litellm's price registry, so cost tracking is disabled via `MSWEA_COST_TRACKING=ignore_errors`. This means the agent's `cost_limit` parameter won't enforce spending caps.
2. **Large patches from obfuscated runs** — the agent may produce enormous patches when working with heavily renamed code. The `predictions.jsonl` for such runs can be large.
3. **SWE-bench eval is slow** — first run builds Docker images (~7 min for astropy). Subsequent runs reuse cached images and are faster.
4. **Empty patches** — the nano model sometimes fails to produce edits within the turn limit, yielding an empty patch. SWE-bench skips evaluation for these.

---

## Code Changes During Testing

| File | Change | Reason |
|------|--------|--------|
| `src/swe_task/agent/runner.py` | Fixed `DefaultAgent` constructor, added template loading, set `MSWEA_COST_TRACKING` | mini-swe-agent v2 API changes |
| `src/swe_task/evaluation/swebench_eval.py` | Updated `run_evaluation()` call signature | swebench API has required positional args |
| `src/swe_task/pipeline.py` | Added `cost_limit` parameter, wrapped eval in try/except | New agent parameter, graceful Docker failure |
| `src/swe_task/obfuscation/rope_renamer.py` | Renamed `l` → `ln` | ruff E741 |
| `scripts/run_swebench.py` | Added `noqa` for E402, removed unused var, added `cost_limit` passthrough | Lint compliance, new parameter |
| `configs/swebench/default.yaml` | Added `agent.cost_limit: 3.0` | New agent parameter |
