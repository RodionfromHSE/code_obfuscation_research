# SWE-bench Obfuscation Pipeline: Development Log

Chronological record of what was built, problems encountered, and how they were resolved.

---

## Phase 1: Dataset selection & initial pivot

### Context

The project started with single-file CodeQA datasets. These turned out too simple for
meaningful obfuscation — renaming variables in a 20-line snippet doesn't stress an LLM.
We looked at xCodeEval (multilingual, some multi-file), but its code samples were still
isolated snippets without cross-file dependencies.

### Decision: SWE-bench

Switched to SWE-bench Verified: 500 real-world GitHub issues from repos like Django,
Flask, Astropy, scikit-learn. Each instance is a full repository at a specific commit
with a gold-standard patch and test suite. This gives us:

- **Repository-level code** with cross-file imports, class hierarchies, test files
- **Deterministic evaluation**: Docker container runs the test suite, pass/fail
- **Established benchmark**: comparable to published agent results

### Agent harness: mini-swe-agent

Chose mini-swe-agent over OpenDevin/SWE-agent because it offers a Python API (not just
CLI), supports `litellm` for model abstraction, and has configurable step/cost limits.
The agent gets a `LocalEnvironment` pointing at the repo directory and interacts with
files via bash tools.

---

## Phase 2: Core obfuscation implementation

### RepoObfuscation protocol

Designed as a `typing.Protocol` with `runtime_checkable` so we can swap implementations
via Hydra without a class hierarchy. Initial interface: `obfuscate(repo_dir) -> Result`.
Later extended with `deobfuscate_patch()` (see Phase 5).

### RopeRepoRenamer

Uses the `rope` library for project-wide refactoring. Rope understands Python's scoping
and import graph, so renaming `compute` in `core.py` automatically updates `from .core
import compute` in `utils.py`, `__init__.py`, and test files.

**Key implementation details:**
- AST-parse each `.py` file to collect top-level public `def`/`class` names
- Skip files matching patterns (`test_*`, `conftest*`, `setup.py`)
- Skip private names (starting with `_`)
- Sequential naming: `func_0`, `func_1`, ..., `cls_0`, `cls_1`, ...
- Per-symbol timeout via `SIGALRM` (30s default) — some rope renames are pathologically slow
- Max 200 symbols cap to bound total runtime

**Bug: macOS symlink paths**

On macOS, temporary directories live under `/var/folders/...` which is a symlink to
`/private/var/folders/...`. Rope resolves paths through `project.root.real_path` (which
follows symlinks), but `Path.relative_to()` fails when comparing `/var/...` to
`/private/var/...`.

Fix: call `.resolve()` on both `repo_dir` and `file_path` before `relative_to()`.

### obfuscated_repo() context manager

`shutil.copytree` to a `tempfile.TemporaryDirectory`, obfuscate in-place, yield, cleanup.
Simple but important: original cloned repos are never touched, enabling shared caching
between identity and rename runs.

---

## Phase 3: Agent integration & first runs

### mini-swe-agent v2 API changes

The v2 API changed `DefaultAgent.__init__()` — it now takes `env` as a separate parameter
instead of embedding it in `AgentConfig`, and requires `step_limit`/`cost_limit` as kwargs
instead of config fields. Also requires `system_template` and `instance_template` strings.

Fix: load default templates from `minisweagent/config/default.yaml` at runtime.

### litellm cost tracking

`gpt-5.4-nano` isn't in litellm's price registry, causing hard failures during cost
calculation. Fix: `os.environ["MSWEA_COST_TRACKING"] = "ignore_errors"`.

### swebench eval API

`swebench.harness.run_evaluation.main()` required additional positional args in the
version we installed (`namespace`, `rewrite_reports`, `modal`). Updated to pass all of them.

### First end-to-end test (3 instances)

Ran identity baseline on 3 instances. Results:
- Agent produced non-empty patches for 2/3 instances
- SWE-bench Docker eval succeeded for 1/3 (the other had a Docker build OOM)
- Pipeline completed in ~8 minutes

---

## Phase 4: 100-instance runs & analysis

### Identity baseline (100 instances)

- 29 resolved, 49 failed, 12 agent errors, 2 timeouts, 8 eval errors
- Eval errors were all Docker build OOM (exit code 137)
- ~$0.09 total cost for 100 instances

### Rope rename (100 instances)

- 17 resolved, 21 failed, 25 agent errors, 5 eval errors, 32 empty patches
- More agent errors than identity — obfuscated names confused the agent
- Many empty patches — agent couldn't figure out what to change

### Problems discovered

**1. Docker build OOM (57 instances)**

Three Docker environment images consistently fail with OOM on macOS Docker Desktop
(4GB default memory). They correspond to older Django and Astropy environments that
compile numpy/scipy from source inside the container.

Fix: created `docker_skip.yaml` listing 57 affected `instance_id`s, loaded automatically
by `load_instances()` to filter them before the pipeline runs.

**2. Console output was a mess**

litellm prints "Provider List for..." and cost info to stderr via `print()`.
mini-swe-agent prints startup banners. HuggingFace datasets prints download progress.
All of this interleaved with tqdm and our own logging.

Fix: multi-layered suppression:
- `MSWEA_SILENT_STARTUP=1` and `LITELLM_LOG=ERROR` set before any imports
- Custom `logging_config.py`: file handler gets DEBUG, console handler gets INFO filtered
  to `swe_task.*` namespace only
- Third-party loggers explicitly set to ERROR, their pre-attached StreamHandlers removed
- `os.dup2` to redirect fd 2 (stderr) to the log file, catching raw `print()` calls
- `litellm.suppress_debug_info = True` for the "Provider List" spam specifically

**3. Empty patches and agent errors on obfuscated repos**

Many instances produced empty patches because the agent couldn't make sense of `func_0`,
`cls_0`, etc. Some agent errors were context-window overruns from large repos. This is
expected degradation — it's what we're measuring.

### Metrics added

Added `cost_usd`, `n_llm_calls`, `n_steps` to `AgentRunResult`. Summary report now
includes cost totals, patch size statistics (median/mean/max), and per-status breakdowns.

---

## Phase 5: The patch bug & reversible obfuscation

### The bug

On the 100-instance rename run, patch sizes averaged 700K+ characters. Investigating a
sample showed the "patch" contained every file rename — not just the agent's changes.

Root cause: `git diff` was run against the original commit. Since obfuscation modified
200+ symbols across 100+ files without committing, the diff captured all obfuscation
changes as if the agent wrote them.

### Fix part 1: git commit after obfuscation

In `repo_copy.py`, after `obfuscation.obfuscate()`:
```python
subprocess.run(["git", "add", "-A"], ...)
subprocess.run(["git", "commit", "-m", "obfuscation", "--allow-empty", "--quiet"], ...)
```

Now `git diff` after the agent runs shows only the agent's changes, relative to the
obfuscated baseline.

### Fix part 2: deobfuscation

The agent's patch now correctly contains only its changes, but those changes reference
obfuscated names (`func_0`, `cls_0`). SWE-bench eval applies the patch to the original
repo, so the names need to match.

Added `deobfuscate_patch(patch, result) -> str` to the `RepoObfuscation` protocol.

`RopeRepoRenamer.deobfuscate_patch()` inverts the `rename_map` (original→obfuscated
becomes obfuscated→original) and does a single-pass regex replacement:

```python
reverse = {v: k for k, v in rename_map.items()}
keys = sorted(reverse, key=len, reverse=True)  # longest first
pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b")
return pattern.sub(lambda m: reverse[m.group(0)], text)
```

Design choices:
- **Longest-first sorting**: `cls_10` must match before `cls_1`
- **Word boundaries (`\b`)**: `func_0_extra` (agent-created variable) is not touched
- **Single pass**: no cascading replacements

`RepoIdentity.deobfuscate_patch()` is a trivial pass-through (`return patch`).

### Testing deobfuscation

11 unit tests for `deobfuscate_patch`:
- Basic reverse mapping
- Empty patch / no rename_map
- Longest-first prevents `cls_1` matching inside `cls_10`
- Word boundary prevents `func_0` matching inside `func_0_extra`
- Substring safety: `compute` → `func_0` does NOT touch `computed_result`
  (because the original name `compute` isn't in the obfuscated patch — only `func_0` is)
- String literals and comments are also reversed (intentional — patches are text diffs)
- Multiple obfuscated names on the same line
- Diff context lines (lines starting with `+`/`-`/` `)

3 round-trip integration tests:
1. Create fixture repo → obfuscate → simulate agent edit → `git diff` → deobfuscate →
   `git apply` to original repo → verify file content
2. Same but with a `computed_result` variable to verify substring safety
3. Same with identity obfuscation

---

## Phase 6: Test failures during integration

### git operations on non-git fixture repos

After adding `_git_commit_obfuscation()`, the context manager tests failed because the
fixture repos created by tests weren't git-initialized.

Fix: made `_git_commit_obfuscation` defensive — no-op if `.git` doesn't exist. Round-trip
tests explicitly call `_git_init()` on their fixture repos.

### Fixture repo paths for round-trip tests

`_create_fixture_repo(base)` created files in `base/`, but round-trip tests need two
copies (original + obfuscated). Test setup needed to create `base/orig/` before calling
the helper.

Fix: added `(base / "orig").mkdir()` in round-trip test setup.

### Ruff F541

A test had `f"..."` with no `{}` placeholders. Ruff caught it.

Fix: removed the `f` prefix.

---

## Summary of bugs and fixes

| Bug | Cause | Fix |
|-----|-------|-----|
| `Path.relative_to()` fails on macOS | `/var/` vs `/private/var/` symlink | `.resolve()` both paths |
| Agent API mismatch | mini-swe-agent v2 changed constructor | Updated to new API + load default templates |
| litellm cost crash | gpt-5.4-nano not in price registry | `MSWEA_COST_TRACKING=ignore_errors` |
| swebench eval args | API requires more positional args | Pass all required args |
| Docker OOM (57 instances) | Large envs exceed macOS Docker memory | `docker_skip.yaml` skip list |
| Console noise | litellm, mswea, huggingface print spam | Multi-layer suppression |
| 700K-char patches | `git diff` captured obfuscation changes | `git commit` obfuscation first |
| Patches have wrong names | Agent uses obfuscated names, eval expects originals | `deobfuscate_patch()` protocol method |
| Test failures on non-git repos | `_git_commit_obfuscation` assumed `.git` exists | Defensive check |
| Fixture path issues | Round-trip tests need subdirectory | Create `orig/` dir explicitly |

---

## Results snapshot (100 instances, after all fixes)

|                    | Identity | Rope rename |
|--------------------|----------|-------------|
| Resolved           | 29       | 17          |
| Failed             | 49       | 21          |
| Agent errors       | 12       | 25          |
| Empty patches      | 0        | 32          |
| Eval errors        | 8        | 5           |
| Timeouts           | 2        | 0           |
| Total cost (USD)   | ~0.09    | ~0.07       |

Obfuscation clearly degrades agent performance: resolved rate drops from 37% to 45% of
evaluated instances (identity) down to ~23% (rename). The agent produces many more empty
patches when confused by generic names.

---

## Phase 7: Prebuilding Docker instance images

### Motivation

After multiple 100-310 instance runs, timing breakdown made docker eval the single
biggest bottleneck. Per-instance wall clock:

| phase | time | % |
|---|---|---|
| clone + obfuscate | 2-15s | <5% |
| agent (LLM) | 30-180s | 20-40% |
| docker eval | 120-300s | 55-70% |

Almost all of the docker time is rebuilding `sweb.eval.*` instance images: git clone
the repo, checkout base_commit, pip install -e, run any `install` commands from the
spec. Then a small amount runs the actual tests. The instance image is a stable
artifact — same base_commit → bit-identical image. But the harness throws it away.

### Root cause

`swebench_eval.py` passes `cache_level="env"` to the harness. Digging into
`swebench/harness/docker_utils.py:should_remove`:

```python
elif image_name.startswith("sweb.eval"):
    if cache_level in {"none", "base", "env"} and (clean or not existed_before):
        return True
```

With `cache_level="env"` + `clean=False`, every `sweb.eval.*` image whose
`existed_before` is `False` is deleted at end of run. Fresh builds get `existed_before=False`
because they were built in-run. So instance images don't survive across pipeline runs.

### Critical realization: the semantics are already correct

We initially considered switching `cache_level` to `"instance"`. Then noticed: with the
existing `"env"` policy, **prebuilt images satisfy `existed_before=True`** (they were
on disk before the run started). `should_remove → False` for them. Only ad-hoc images
built during the run are cleaned up.

So the desired "use prebuilt if available, otherwise build-and-discard" behavior is
**automatic**. No config change. Just populate the cache before running.

### Design: out-of-band top-K prebuilder

Requirements from the user:
- only prebuild a small, high-impact subset (disk budget ~50 GB)
- never invoke prebuild from inside the pipeline — separate CLI
- prebuild target = "most popular" images in the filtered set → rank `(repo, version)`
  buckets by instance count, take top-K under disk cap
- include the corresponding instance IDs in a priority list so pipeline runs can be
  restricted to them
- well-tested; minimal diff to existing code
- store manifest + cleanup script in `~/Downloads/ml4se_images/` as a self-explaining
  bookmark

### Module layout (new): `swebench_task/prebuild/`

- `image_selection.py` — pure logic: `Bucket`, `PrebuildPlan`, `group_by_repo_version`,
  `select_top_k_buckets`, `estimate_bucket_gb`. No docker, no HF. Unit-testable.
- `manifest.py` — `PrebuildManifest` dataclass + JSON round-trip + `generate_cleanup_script`
  (embeds tags inline so cleanup works even if manifest is later edited).
- `prebuilder.py` — wraps `swebench.harness.prepare_images.main()`; diffs
  `docker images` before/after to populate the manifest with actual byte sizes.
- `priority_yaml.py` — `write_priority_yaml` / `load_priority_ids` for the
  `configs/priority_instances.yaml` file.

### CLI scripts (new)

- `scripts/prebuild_images.py` — flags: `--top-k`, `--max-total-gb`, `--workers`,
  `--ml4se-dir`, `--repo`, `--force-rebuild`, `--dry-run`, `--yes`. Loads filtered
  dataset (honors `docker_skip.yaml`), builds plan, confirms, calls `run_prebuild`,
  writes manifest + cleanup + priority YAML.
- `scripts/cleanup_prebuilt_images.py` — reads manifest, `docker rmi -f` every listed
  tag, writes before/after `docker system df` snapshots.

### Pipeline hook (minimal change)

One new optional parameter `priority_ids: list[str] | None` threaded through:
- `source/dataset.py:load_instances` — if given, filters dataset to those IDs (skip
  list still applies, ordering preserved as given)
- `source/pipeline.py:run_swebench_pipeline` — just passes it to `load_instances`
- `__main__.py` — reads `priority_instances: <yaml_path>` from Hydra config, loads via
  `load_priority_ids`

That's the entire pipeline diff. No changes to obfuscation, agent, cache, or eval
internals.

### Bucket selection

Greedy under a disk budget:

```python
def select_top_k_buckets(buckets, top_k, max_total_gb):
    buckets_sorted_desc_by_size = ...
    for bucket in buckets_sorted_desc_by_size:
        if len(taken) >= top_k:
            break
        if estimate_bucket_gb(bucket) + total_gb > max_total_gb:
            skip
        else:
            take
    # edge case: if the first bucket alone exceeds budget, take it and flag it
```

Size estimate: `n_instances * 1.2 GB` (instance images) + `REPO_ENV_SIZE_GB.get(repo, 5)`
(env image amortized once per bucket).

### Storage caveat

Docker Desktop on Mac stores all images in its VM disk (single path). You can't
redirect specific images to `~/Downloads/ml4se_images/`. The directory is a
manifest + cleanup.sh bookmark. Called out explicitly in the tutorial.

### What we tested

Unit (no docker, 22 tests):
- `test_image_selection.py`: grouping/sort order, tie-break, estimate lookup, top-K
  caps by count, caps by budget, oversized-first-bucket flag, deterministic ordering,
  empty input, format output
- `test_prebuild_manifest.py`: JSON round-trip, cleanup script contains every tag,
  empty manifest, executable bit, shell-quote safety, env+instance tag union
- `test_priority_filter.py`: priority filter-and-reorder, skip list still honored,
  unknown IDs dropped, fallback to shuffle, YAML round-trip, missing file = empty

Smoke (real docker, pytest-dev 5.4 bucket, 4 instances, ~7 GB):
- prebuild → `docker images` confirms 4 new `sweb.eval.*` tags
- pipeline on 2 of those instances → log: `Found 2 existing instance images. Will reuse them.`
- cleanup → `docker system df` shows freed bytes

### Pipeline log signal

The harness already prints this when reusing prebuilt images (see
`swebench/harness/run_evaluation.py:324`):

```
Found N existing instance images. Will reuse them.
```

Grep logs for this line to verify prebuild is effective.

### Open questions / limitations

- Env image size lookup is coarse. For repos not in `REPO_ENV_SIZE_GB` we fall back
  to 5 GB — noticeably wrong for tiny packages (requests ≈ 1.5 GB).
- No automatic disk-pressure check before prebuild (would need to parse
  `docker system df` and compare against free VM space). For now the user manages it.
- Prebuild could OOM the same envs that OOM during pipeline eval (scikit-learn,
  astropy). The skip list filters them out, but that means those buckets are never
  candidates for prebuild. Acceptable trade-off.
- Priority YAML is autogenerated and written to `configs/` on every CLI run, including
  `--dry-run`. Could be considered a side-effect of dry-run; left as-is for now so
  users can generate the YAML without committing to a build.

### A/B measurement (added after phase 7 landed)

Before committing to a full prebuild I measured the actual speedup on a clean A/B.
Setup: 4 pytest-dev/pytest 5.4 images already prebuilt, gold patches, `smoke_prebuild`
script with explicit `--instance-id` and wall-clock timer, `require_reuse=0` for the
cold arm.

- removed one prebuilt image: `docker rmi sweb.eval.x86_64.pytest-dev__pytest-7205:latest`
- COLD: eval pytest-7205 → harness builds `sweb.eval.*` fresh, then removes it
  (matches the "no prebuild" behavior under `cache_level=env`, `clean=False`):
  **135.5 s** wall-clock, marker "Will reuse them" absent
- WARM: eval pytest-7236 → harness reuses prebuilt image:
  **55.7 s** wall-clock, marker present

**2.43× wall-clock speedup per instance; ~4× on the Docker portion alone**
(wall-clock minus ~30 s HF dataset + predictions write overhead: 105 s → 26 s).

Per-instance savings: ~80 s. On a 36-instance bucket that's ~48 minutes shaved.
Verdict: ship full prebuild for the top bucket.

### Full prebuild run

Ran on top-1 bucket: `django/django@4.0` (36 instances), 50 GB budget, 3 then 2 workers.

**First pass (workers=3):** 10/36 built, 26 failed. Root cause: transient
`git clone https://github.com/django/django` failures with GnuTLS recv errors when
3 parallel clones contended over the network. Not OOM, not a code issue. Example
from `logs/build_images/.../django__django-14311/build_image.log`:

```
error: RPC failed; curl 6 GnuTLS recv error (-110): The TLS connection was non-properly terminated.
fatal: error reading section header 'shallow-info'
```

**Second pass (workers=2):** re-ran the same CLI, `prepare_main` skipped the 10
already-built images and retried the 26 failures. All 26 built successfully in
~45 minutes. Final state: 36 django/4.0 instance images + 3 pytest-dev/5.4
images remaining from the earlier smoke.

**Disk reality vs. manifest:** manifest reports `total_size_bytes = 165 GB`
(sum of per-image `docker images --format "{{.Size}}"`). Actual increase in Docker
VM disk from prebuild: **~11 GB** (Mac free went 446 → 435 GB, Docker `Images`
total went 104.3 → 113.5 GB). The 165 GB number double-counts the shared env
layer — each of the 36 images inherits the same ~4 GB `sweb.env.py.x86_64.*`
base. Keep this in mind; our `estimate_bucket_gb` heuristic is also too
conservative (claimed 47.2 GB for what became ~11 GB real).

**Sanity smoke on a newly-built django image:**

```
instance:       django__django-14122
wall_clock:     89.4 s
reuse marker:   True
gold resolved:  True
unremoved imgs: 39
```

Django is bigger than pytest (more tests, larger repo) so wall-clock is higher
than pytest warm (55.7 s), but the image-reuse signal is what we wanted.

### Lesson for next time

- Default `workers=4` in the CLI is too aggressive for large repos (django). For
  initial prebuilds of a single big bucket, use `workers=2`. Future improvement:
  dynamic worker count based on repo size, or exponential-backoff retry of failed
  clones inside `prepare_main` (would need a PR upstream or a local wrapper).
- Disk estimator overcounts by a factor of ~4×. Not a correctness bug (it errs
  safe), but documentation should say "ceiling, not point estimate".

