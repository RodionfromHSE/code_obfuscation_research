# Deobfuscation E2E Verification Report

**Date:** 2026-04-10
**Model:** `gpt-5.4-nano-2026-03-17`
**Instances:** `astropy__astropy-12907`, `astropy__astropy-13033` (SWE-bench Verified)

---

## 1. What was tested

Full pipeline with the new reversible obfuscation protocol:
```
clone repo -> obfuscate (rope rename, 200 symbols) -> git commit obfuscation
  -> run agent -> git diff -> deobfuscate_patch() -> save clean patch
  -> SWE-bench Docker eval on original repo
```

Both identity (baseline) and rope_rename runs on 2 instances.

## 2. Bug found and fixed (prior to this test)

`git diff` was capturing the full obfuscation diff (700K+ chars) instead of just the agent's changes. Two fixes applied:

1. **Git commit after obfuscation** — `_git_commit_obfuscation()` in `repo_copy.py` stages and commits all obfuscation changes so `git diff` only captures agent work.
2. **`deobfuscate_patch()`** — new protocol method reverses obfuscated names (`func_0` -> `compute`) in the patch via regex word-boundary replacement before submission to SWE-bench eval.

## 3. Results

| Instance | Experiment | Symbols Renamed | Patch Size | Contains `func_`/`cls_`? | Eval Status |
|---|---|---|---|---|---|
| astropy-12907 | identity | 0 | 0 chars | N/A | empty_patch |
| astropy-13033 | identity | 0 | 2069 chars | No | failed |
| astropy-12907 | rope_rename | 200 | 0 chars | No | empty_patch |
| astropy-13033 | rope_rename | 200 | 0 chars | No | empty_patch |

### Key observations

- **No obfuscated names leak into predictions.jsonl** — verified by scanning all prediction patches.
- **Identity patch for 13033 is clean** — 37 lines, 2069 chars, modifies `astropy/timeseries/core.py`. Proper diff, no noise.
- **Rename patches are genuinely empty** — the agent made 10 LLM calls on the obfuscated repo but produced no file changes. Previously this would have appeared as 700K+ chars of obfuscation diff.
- **Docker eval ran successfully** on the identity patch (failed = incorrect fix, not infra error).
- **Docker eval correctly skipped** instances with empty patches.
- **Stdout was clean** — only pipeline-level progress lines, no litellm spam.

## 4. Unit test coverage

25 tests passing, including:

- **6 deobfuscation unit tests** (pure string logic):
  - Basic reverse replacement
  - Empty patch / no rename_map passthrough
  - `cls_1` vs `cls_10` longest-first ordering
  - Word boundary: `func_0_extra` not replaced, `func_0()` is
  - Substring safety: `computed_result` untouched when `compute` -> `func_0`
  - Names in string literals and comments are reversed
  - Agent-created variables with obfuscated prefix survive
  - Multiple obfuscated names on same line
  - Diff context lines also reversed

- **3 round-trip integration tests**:
  - Rename: obfuscate -> edit -> diff -> deobfuscate -> `git apply` to original
  - Rename with substring variable (`computed_result`): same flow, verifies no mangling
  - Identity: passthrough, `git apply` works

## 5. Cleanup

All test artifacts removed (`e2e_identity_check/`, `e2e_rename_check/`, associated logs and swebench reports).

## 6. Conclusion

The reversible obfuscation protocol works correctly. Patches submitted to SWE-bench eval are now:
- In terms of original (non-obfuscated) names
- Only contain the agent's actual changes (not the obfuscation diff)
- Safe against substring collisions and word-boundary edge cases

Previous run data (700K patches, ~2% "resolve" rate for rename) was invalid — the patches were obfuscation diffs, not agent fixes. New runs will produce meaningful measurements of how obfuscation degrades agent performance.
