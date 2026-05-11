# Dataset & Harness Report: Beyond Single-File Benchmarks

## 0. The problem with current datasets

HumanEval, CodeQA, xCodeEval — all **single-file, single-function** tasks.
Obfuscating `def add(a, b)` is toy-level: rename two vars and you're done.
Real code privacy concerns involve **repositories**: cross-file dependencies, class hierarchies, imports, configs. That's where obfuscation actually matters and where the signal is interesting.

---

## 1. xCodeEval: quick summary (and why it's not the answer)

Source: [NTU-NLP-sg/xCodeEval](https://huggingface.co/datasets/NTU-NLP-sg/xCodeEval) (ACL 2024). ~25M samples, 7514 Codeforces problems, 17 languages.

### Tasks

| Task | Input → Output | Eval | Has code input? |
|---|---|---|---|
| Program Synthesis | NL problem → code | exec (pass@k) | no |
| APR | buggy code + NL → fixed code | exec (pass@k) | **yes** |
| Code Translation | code (lang A) → code (lang B) | exec (pass@k) | **yes** |
| Tag Classification | code → algorithm tags | macro-F1 | yes |
| Code Compilation | code → compilable? | binary | yes |
| Retrieval (x2) | code/NL → code | Acc@k | yes |

**Best for obfuscation: APR** — model receives `bug_source_code` as input, we obfuscate it, eval is deterministic (hidden unit tests via stdin/stdout).

### Why it falls short

- **Still single-file.** Competitive programming = one file, stdin/stdout. No imports, no classes, no multi-file reasoning.
- Obfuscation surface is tiny: typically 10–30 lines of algorithmic code with single-char variables that are already unreadable.
- Doesn't test what we actually care about: can the model understand **real codebases** after obfuscation?

---

## 2. What we actually want

| Requirement | Why |
|---|---|
| **Repository-level** samples | real obfuscation surface: cross-file refs, class hierarchies, imports |
| **Code is the input** | model must *read* the code to solve the task — obfuscation directly impacts this |
| **Deterministic eval** | unit tests, not LLM-judge |
| **Agent harness exists** | don't build an agent from scratch — plug in model API, get predictions |
| **Python** | our perturbations are Python-only (libcst-based) |

---

## 3. Candidates

### 3a. SWE-bench (Verified / Lite) — best fit

[princeton-nlp/SWE-bench](https://huggingface.co/datasets/princeton-nlp/SWE-bench) | [SWE-bench Verified](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified)

**What it is:** 2,294 real GitHub issues (Verified: 500 human-validated) from 12 popular Python repos (django, flask, sympy, scikit-learn, matplotlib, etc.). Each task: given a `problem_statement` (issue text), produce a `patch` that makes `FAIL_TO_PASS` tests pass without breaking `PASS_TO_PASS` tests.

**Sample structure:**
```json
{
  "instance_id": "django__django-16379",
  "repo": "django/django",
  "base_commit": "a1b2c3d...",
  "problem_statement": "FileBasedCache has race condition...",
  "patch": "diff --git a/django/core/cache/backends/filebased.py ...",
  "test_patch": "diff --git a/tests/cache/tests.py ...",
  "FAIL_TO_PASS": "[\"test_cache_race_condition\"]",
  "PASS_TO_PASS": "[\"test_cache_set\", \"test_cache_get\", ...]",
  "version": "4.2",
  "hints_text": "..."
}
```

**Why it's the best fit:**
- **Repo-level**: agent must navigate full Django/scikit-learn/etc. codebases (thousands of files)
- **Code is the input**: the agent reads source files to understand context, locate the bug, write a fix
- **Deterministic eval**: pass/fail = do the tests pass? No LLM judge needed
- **Python only**: all 12 repos are Python — our perturbations apply directly
- **Agent harnesses exist**: SWE-agent, OpenHands, and mini-swe-agent all solve this out of the box

**The obfuscation experiment:**
1. Clone the repo at `base_commit`
2. Apply our perturbations (rename_symbols, etc.) to the *entire repository* (or relevant files)
3. Run the agent (SWE-agent) with the obfuscated repo
4. Measure: `resolved_rate_obfuscated` vs `resolved_rate_original`

### 3b. Agent harnesses

| Harness | What it does | Integration effort |
|---|---|---|
| **[SWE-agent](https://swe-agent.com)** | lightweight CLI agent, ACI tools (bash, file viewer, editor, search). Config: point `model.name` to any OpenAI-compatible API via litellm | **low** — `sweagent run --model.name=openai/gpt-5.4-nano --data_path=instance.json` |
| **[OpenHands](https://docs.openhands.dev)** | heavier platform, web UI, multi-agent, Docker sandboxing | medium — more features but more setup |
| **[mini-swe-agent](https://mini-swe-agent.com)** | ~100-line rewrite of SWE-agent, same perf | **lowest** — easy to hack |

**SWE-agent is the recommendation.** It:
- Takes a model API (via litellm — any OpenAI-compatible endpoint works)
- Takes a SWE-bench instance (or any GitHub issue)
- Spins up a Docker container with the repo
- Runs the agent loop: think → tool-call (bash/edit/search) → observe → repeat
- Outputs a `model_patch` (git diff)
- You feed that patch to `swebench.harness.run_evaluation` → deterministic pass/fail

### 3c. Other repo-level benchmarks (less relevant but notable)

| Benchmark | Focus | Why less ideal |
|---|---|---|
| **RepoBench** | code completion with cross-file context | completion, not agentic task |
| **CrossCodeEval** | cross-file code completion, multilingual | same — completion |
| **ExecRepoBench** | repo-level completion with unit test eval | closer, but still completion |
| **FEA-Bench** | feature addition from PRs | newer, less tooling |
| **CodeScaleBench** | enterprise-scale multi-repo | overkill |

### 3d. Related work: OBFUSEVAL (ICSE 2025)

[zhangbuzhang/ObfusEval](https://github.com/zhangbuzhang/ObfusEval) — "Unseen Horizons" paper.

Directly related to our project: they apply 3-level obfuscation (symbol/structure/semantic) to code generation benchmarks and show up to 62.5% drop in pass rate. But:
- Their benchmark is 1,354 cases from 5 OSS projects — not truly repo-level agentic tasks
- They evaluate code *generation*, not code *comprehension + repair* in a full repo context
- Our project can go further by applying obfuscation to **SWE-bench repos** and measuring agent performance

---

## 4. Proposed integration plan

### Phase 1: SWE-bench + SWE-agent (the core experiment)

```
obfuscated repo ──→ SWE-agent (with task model) ──→ model_patch ──→ swebench eval harness ──→ pass/fail
     ↑                                                                        ↓
perturbations                                                          resolved_rate
(rename_symbols, etc.)
```

**Components:**

| What | How | Effort |
|---|---|---|
| Load SWE-bench Verified | `load_dataset("SWE-bench/SWE-bench_Verified")` | trivial |
| Clone + obfuscate repo | `git clone` at `base_commit`, run perturbations on `.py` files | medium — need to handle partial AST failures gracefully |
| Run SWE-agent | `sweagent run` with our model config, pointed at obfuscated repo | low — it's a CLI tool |
| Evaluate | `swebench.harness.run_evaluation` on predictions JSONL | low — existing tool |
| Compare | `resolved_rate(noop)` vs `resolved_rate(rename_symbols)` vs ... | trivial |

### Phase 2: Integration with existing project infra

The current project pipeline (`run_pipeline` → `eval_pipeline`) is designed for single-sample LLM calls. SWE-bench is an *agent* task (multi-turn, tool-use). Two options:

**Option A: Standalone script (recommended for now)**
- New `scripts/run_swebench.py` that orchestrates: load dataset → clone → obfuscate → run SWE-agent → collect patches → run eval
- Reuse `Perturbation` protocol and existing perturbation implementations
- Reuse Hydra configs for perturbation selection
- Don't try to force it through `run_pipeline` — the agent loop is fundamentally different from single-shot LLM calls

**Option B: Adapt pipelines (later, if needed)**
- Generalize `TaskDefinition` to support multi-turn agent tasks
- Add `AgentRuntime` alongside `LLMRuntime`
- Overkill for now

### What to reuse from existing project

| Component | Reuse? |
|---|---|
| `Perturbation` protocol + `rename_symbols` | **yes** — apply to repo files |
| `PerturbationInput` / `PerturbationResult` | **yes** — one per file |
| Hydra config pattern | **yes** — perturbation selection, model config |
| `LLMRuntime` | **no** — SWE-agent has its own model interaction |
| `TaskDefinition` | **no** — agent task ≠ single-shot prompt |
| `humaneval_exec.py` pattern | **no** — SWE-bench has its own eval harness |

---

## 5. Effort estimate

| Phase | Work | Time |
|---|---|---|
| Install SWE-agent + SWE-bench harness | pip/uv install, Docker setup | 0.5 day |
| Script: clone + obfuscate repo at base_commit | iterate `.py` files, apply perturbation, handle parse errors | 1–2 days |
| Script: run SWE-agent on obfuscated repo | CLI wrapper, collect predictions JSONL | 0.5 day |
| Script: run swebench eval, collect metrics | invoke harness, aggregate resolved_rate | 0.5 day |
| Run experiments: noop vs rename_symbols on Verified-500 | compute time (depends on model cost) | 1–2 days |
| **Total** | | **~4–5 days** |

---

## 6. Risks

- **Perturbation breaks the repo**: renaming symbols across a large repo can break imports/references. Need to either (a) use a whole-repo rename that's import-aware, or (b) only perturb files the agent is likely to read (scope from `patch` field), or (c) accept some breakage and measure its impact.
- **SWE-agent cost**: each instance costs ~$0.50–$2.00 in API calls (depending on model). 500 instances x 2 conditions = ~$500–$2000.
- **Docker requirements**: SWE-bench eval needs Docker. Each instance builds its own container.
- **Obfuscation granularity**: obfuscating the *entire* repo is a different experiment from obfuscating just the *files relevant to the issue*. Both are interesting but should be separate runs.
