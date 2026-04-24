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
