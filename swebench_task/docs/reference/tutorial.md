# Tutorial: How the SWE-bench Obfuscation Pipeline Works

This document walks through the full pipeline step by step: what happens when you run
`python -m swebench_task`, why each stage exists, and what Docker/API calls are involved.

---

## Overview: two-phase architecture

The pipeline has two distinct phases with different infrastructure requirements:

```
Phase 1: Prediction (needs API key, no Docker)
  load dataset -> clone repos -> obfuscate -> run agent -> collect patches

Phase 2: Evaluation (needs Docker, no API key)
  apply patches to original repos -> run test suites -> pass/fail
```

Phase 1 is where you spend API money. Phase 2 is where you spend compute time.
They are sequential in a single run, but conceptually separate — you could generate
predictions today and evaluate them next week.

### Why two phases?

SWE-bench evaluation requires running each project's test suite inside a Docker container
that matches the exact Python/dependency versions from the original GitHub issue.
Building these Docker images is slow and resource-heavy (some need 8GB+ RAM).

The agent, on the other hand, just needs to read files, run commands, and call the LLM API.
It works on a local checkout, not inside Docker.

Keeping them separate means:
- You can iterate on the agent/obfuscation without rebuilding Docker images
- You can evaluate the same predictions with different Docker settings
- If Docker fails (OOM, network), your agent predictions are already saved

---

## Step-by-step walkthrough

### Step 0: Configuration

When you run:
```bash
uv run python -m swebench_task repo_obfuscation=rope_rename samples_limit=3
```

Hydra composes the config from these files:
- `configs/default.yaml` — top-level defaults
- `configs/model/gpt5_4_nano.yaml` — model name + agent limits
- `configs/repo_obfuscation/rope_rename.yaml` — obfuscation class + parameters
- `configs/paths/default.yaml` — where artifacts go

Command-line overrides (`samples_limit=3`) take priority. The fully resolved config
is logged to `swebench_task/artifacts/logs/<experiment>.log`.

### Step 1: Load dataset

```python
instances = load_instances("SWE-bench/SWE-bench_Verified", "test", limit=3)
```

**What happens:**
- Downloads the dataset from HuggingFace (cached after first download in `~/.cache/huggingface/`)
- Each row becomes a `SWEBenchInstance` dataclass with: `instance_id`, `repo`,
  `base_commit`, `problem_statement`, `patch` (gold), `test_patch`, etc.
- Instances in `configs/docker_skip.yaml` are excluded (57 IDs that OOM in Docker)

**No Docker needed.** No API calls. This takes a few seconds.

### Step 2: Clone repository (per instance)

```python
repo_dir = clone_repo(instance, work_dir)
```

**What happens:**
- `git clone https://github.com/{repo}.git` into `swebench_task/artifacts/repos/{instance_id}/`
- `git checkout {base_commit}` to the exact commit where the issue was filed
- Clones are cached: if the directory already exists, this is a no-op

**No Docker needed.** No API calls. First run clones ~100 repos (~10-30 min depending
on network). Subsequent runs reuse cached clones.

### Step 3: Obfuscate (per instance)

```python
with obfuscated_repo(repo_dir, obfuscation) as ctx:
    # ctx.obfuscated_dir is a temp copy with renamed symbols
```

**What happens:**
1. `shutil.copytree` creates a temporary copy of the repo
2. The obfuscation strategy runs on the copy:
   - **identity**: does nothing (baseline)
   - **rope_rename**: uses `rope` to rename up to 200 public functions/classes
     to `func_0`, `func_1`, `cls_0`, etc. across all files
3. `git add -A && git commit` commits the obfuscated state

**Why commit after obfuscation?** So that `git diff` later captures only the agent's
changes, not the 200-symbol rename. Without this, the diff would be 700K+ chars of
rename noise.

**No Docker needed.** No API calls. Rope rename takes 10-60s per instance depending
on repo size. Identity is instant.

### Step 4: Run agent (per instance)

```python
agent_result = run_agent(
    repo_dir=ctx.obfuscated_dir,
    problem_statement=instance.problem_statement,
    instance_id=instance.instance_id,
    model_name="openai/gpt-5.4-nano-2026-03-17",
    max_turns=50,
    cost_limit=3.0,
    timeout_seconds=1200.0,
)
```

**What happens:**
- mini-swe-agent gets a `LocalEnvironment` pointing at the obfuscated repo directory
- The agent receives the `problem_statement` (the GitHub issue text)
- It interacts with the repo via bash commands: reads files, searches code, edits files
- Each turn: agent sends a message, LLM responds with a command, agent executes it
- Continues until: agent says "done", hits `max_turns`, exceeds `cost_limit`, or times out
- A `ThreadPoolExecutor` enforces the wall-clock timeout

**This is where API costs happen.** Each instance costs ~$0.01-$0.10+ depending on model
and turns. The agent runs on your local filesystem, not in Docker.

### Step 5: Extract patch (per instance)

```python
patch = git_diff(repo_dir)
clean_patch = obfuscation.deobfuscate_patch(patch, ctx.result)
```

**What happens:**
1. `git diff` captures everything the agent changed (relative to the post-obfuscation commit)
2. `deobfuscate_patch()` reverse-maps obfuscated names back to originals:
   - `func_0` -> `compute`, `cls_0` -> `DataStore`, etc.
   - Uses single-pass regex with word boundaries: `\b(func_0|cls_0|...)\b`

**Why deobfuscate?** SWE-bench evaluation applies `git apply <patch>` to the *original*
repo (not the obfuscated copy). A patch containing `func_0` where the real code says
`compute` would fail to apply.

**No Docker needed.** No API calls. This is pure string processing, takes milliseconds.

### Step 6: Save predictions

```python
save_predictions(agent_results, predictions_path, model_name)
```

**What happens:**
- Writes `predictions.jsonl` in SWE-bench format: one JSON per line with
  `instance_id`, `model_name_or_path`, and `model_patch`
- Also saves per-instance report JSON files with full details (obfuscation stats,
  agent cost, step count, etc.)

This is the handoff point between Phase 1 and Phase 2.

### Step 7: Evaluate (Docker phase)

```python
eval_results = run_swebench_eval(
    predictions_path=predictions_path,
    dataset_name="SWE-bench/SWE-bench_Verified",
    run_id=experiment_name,
)
```

**What happens:**
1. Calls `swebench.harness.run_evaluation` from the `swebench` pip package
2. For each instance in `predictions.jsonl`:
   a. Builds (or reuses) a Docker image matching the repo's Python version and dependencies
   b. Inside the container: checks out the base commit, applies the agent's patch via `git apply`
   c. Runs the test suite (`pytest` or the repo's test runner)
   d. Checks which tests pass/fail
   e. Compares against `FAIL_TO_PASS` (tests that the gold patch fixes): if they all pass
      now, the instance is "resolved"
3. Writes per-instance `report.json` files under `logs/run_evaluation/<run_id>/`

**This requires Docker.** Each instance builds a container (cached after first build).
Some containers need 4-8GB RAM. Evaluation runs `max_workers=4` instances in parallel.
Total time: ~5-30 min for 100 instances depending on cache state.

**No API calls.** This is pure local computation.

### Step 8: Aggregate and report

```python
save_summary_report(all_reports, summary_path)
```

**What happens:**
- Merges eval results with agent results
- Computes aggregate stats: resolve rate, failure breakdown, cost, patch sizes
- Saves `summary.json` and updates per-instance report JSON files with eval results

---

## Output structure

After a run completes:

```
swebench_task/artifacts/
├── repos/                                    # cached repo clones (shared across runs)
│   ├── django__django-13128/
│   ├── astropy__astropy-12907/
│   └── ...
├── runs/
│   └── swebench_identity/                    # one directory per experiment
│       ├── predictions.jsonl                 # SWE-bench format predictions
│       ├── summary.json                      # aggregate stats
│       └── instance_reports/
│           ├── django__django-13128.json     # full detail per instance
│           └── ...
└── logs/
    └── swebench_identity.log                 # verbose debug log
```

Each instance report JSON contains:
```json
{
  "instance_id": "django__django-13128",
  "status": "resolved",
  "obfuscation_name": "identity",
  "obfuscation": {
    "symbols_renamed": 0,
    "files_modified": 0,
    "rename_map": {},
    "errors": [],
    "skipped": []
  },
  "agent": {
    "instance_id": "django__django-13128",
    "model_patch": "diff --git a/...",
    "timed_out": false,
    "error": null,
    "cost_usd": 0.0,
    "n_llm_calls": 12,
    "n_steps": 6
  },
  "eval": {
    "instance_id": "django__django-13128",
    "resolved": true,
    "error": null
  }
}
```

---

## Common scenarios

### Run without Docker (predictions only)

If Docker isn't running, Phase 1 completes normally and saves predictions.
Phase 2 will fail with a logged error, but you keep all your predictions and
instance reports (with `status: "not_evaluated"`). You can evaluate later by
feeding `predictions.jsonl` to `swebench` directly.

### Reuse cached repos

Repos are cached in `swebench_task/artifacts/repos/`. Delete a repo directory to
force re-clone. All repos are safe to delete — they'll be re-cloned on next run.

### Compare obfuscation strategies

Run the same instances with different obfuscations:
```bash
uv run python -m swebench_task repo_obfuscation=identity experiment_name=exp_identity samples_limit=20
uv run python -m swebench_task repo_obfuscation=rope_rename experiment_name=exp_rename samples_limit=20
```

Both runs share cached repo clones. Compare the `summary.json` files or
instance reports to see the impact.

### Quick smoke test

```bash
uv run python -m swebench_task samples_limit=1
```

Runs one instance end-to-end. Takes ~2-5 min (clone + agent + Docker eval).

---

## What is SWE-bench Verified?

[SWE-bench](https://www.swebench.com/) is a benchmark of 2294 real GitHub issues
from 12 Python repositories (Django, Flask, Astropy, scikit-learn, etc.). Each instance
includes the issue text, the repository at the commit where the issue was filed, a gold
patch that fixes it, and a test that verifies the fix.

[SWE-bench Verified](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified)
is a human-verified subset of 500 instances where annotators confirmed the gold patch
and tests are correct. We use this subset because the full benchmark has noisy labels.

Each instance is identified by `{org}__{repo}-{issue_number}`, e.g. `django__django-13128`.

The benchmark tests an agent's ability to:
1. Understand a bug report or feature request
2. Navigate a large, unfamiliar codebase
3. Identify the relevant files and functions
4. Write a correct patch that passes the test suite

By obfuscating the codebase (renaming symbols to `func_0`, `cls_0`), we make step 2-3
harder and measure how much the agent's performance degrades.

### What does a single SWE-bench instance look like?

Each row in the dataset contains these fields:

| Field | Description |
|-------|-------------|
| `instance_id` | Unique ID, e.g. `astropy__astropy-13453` |
| `repo` | GitHub repo, e.g. `astropy/astropy` |
| `base_commit` | The exact commit hash where the bug exists |
| `problem_statement` | The GitHub issue text — what the user reported. This is what the agent sees |
| `patch` | The gold-standard diff that fixes the bug (human-written, merged PR) |
| `test_patch` | Additional test code added by the PR to verify the fix |
| `FAIL_TO_PASS` | JSON list of test IDs that fail before the fix and pass after |
| `PASS_TO_PASS` | JSON list of test IDs that must keep passing (regression guard) |
| `hints_text` | Optional hints from the issue thread (we don't pass these to the agent) |
| `version` | Library version at that commit |

Concretely, for `astropy__astropy-13453`, the `problem_statement` describes an issue
with HTML table output format not being applied. The gold `patch` adds ~25 lines to
`astropy/io/ascii/html.py`. The `FAIL_TO_PASS` lists a specific test that exercises
the format behavior.

The agent never sees `patch`, `test_patch`, or `FAIL_TO_PASS` — it only gets the
`problem_statement` and access to the repo at `base_commit`.

### When is an instance "resolved"?

An instance is resolved when **all** of these are true:

1. The agent produced a non-empty patch
2. `git apply` successfully applied the patch to the original repo (in Docker)
3. Every test in `FAIL_TO_PASS` now passes (the bug is fixed)
4. Every test in `PASS_TO_PASS` still passes (no regressions introduced)

If any of those fail, the instance is **not resolved**, even if the agent's fix is
partially correct.

### What errors can occur?

Our pipeline tracks these statuses for each instance:

| Status | What happened |
|--------|---------------|
| `resolved` | Agent's patch passed all tests — the fix works |
| `failed` | Agent produced a patch, Docker eval ran, but tests didn't pass. Either the patch was wrong, didn't apply, or introduced regressions |
| `empty_patch` | Agent finished (or hit cost/turn limit) without modifying any files. `git diff` was empty. Common when the agent can't find the relevant code |
| `agent_error` | Agent crashed (exception in mini-swe-agent or litellm). Rare |
| `agent_timeout` | Agent exceeded `timeout_seconds` wall-clock limit. The `ThreadPoolExecutor` kills it |
| `eval_error` | Docker evaluation failed, usually because the Docker image couldn't be built. Exit code 137 = OOM. This is why we have `docker_skip.yaml` |
| `not_evaluated` | Agent ran successfully but Docker eval was skipped (e.g. Docker not running) |

In our 100-instance runs, the breakdown was roughly:

- ~30-45 `failed` (most common — agent tries but gets it wrong)
- ~20-28 `empty_patch` (agent gives up)
- ~20-32 `resolved` (agent nails it)
- ~1-3 `eval_error` (Docker infra issue)
- 0-1 `agent_timeout` (rare with 1200s limit)
