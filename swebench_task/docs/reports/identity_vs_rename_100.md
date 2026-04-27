# Identity vs. Rope Rename: 100-Instance Comparison

**Date:** 2026-04-10 (artifacts cleaned 2026-04-16)
**Model:** `gpt-5.4-nano-2026-03-17` via mini-swe-agent v2.2.8
**Dataset:** SWE-bench Verified, first 100 non-skipped instances
**Agent config:** `max_turns=50`, `cost_limit=3.0`, `timeout=1200s`
**Obfuscation:** rope rename with `max_symbols=200`, `per_symbol_timeout=30s`

---

## Summary

| Metric | Identity | Rope Rename | Delta |
|--------|----------|-------------|-------|
| **Resolved** | 32 | 20 | -12 |
| **Failed** (eval ran, tests didn't pass) | 45 | 50 | +5 |
| **Empty patch** (agent produced no edits) | 20 | 28 | +8 |
| **Agent timeout** | 0 | 1 | +1 |
| **Eval error** (Docker build failure) | 3 | 1 | -2 |
| Evaluated (resolved + failed) | 77 | 70 | -7 |
| Resolve rate (of evaluated) | 32/77 = **41.6%** | 20/70 = **28.6%** | **-13.0pp** |
| Resolve rate (of total) | 32% | 20% | -12pp |
| Non-empty patches | 80 | 71 | -9 |
| Median patch size (chars) | 1196 | 1187 | ~same |
| Mean patch size (chars) | 1520 | 1733 | +213 |
| Max patch size (chars) | 9069 | 21451 | +12382 |
| LLM calls | 1479 | 1482 | ~same |
| Avg symbols renamed | 0 | 173.8 | - |
| Obfuscation had errors | 0 | 14 | +14 |

Obfuscation dropped the resolve rate from 41.6% to 28.6% (of evaluated instances), a relative decrease of ~31%.

## Per-instance status transitions

What happened to each instance when moving from identity to rename:

| Identity status | Rename status | Count |
|-----------------|---------------|-------|
| failed | failed | 27 |
| resolved | failed | 15 |
| empty_patch | empty_patch | 10 |
| failed | empty_patch | 10 |
| resolved | resolved | 10 |
| empty_patch | failed | 7 |
| failed | resolved | 7 |
| resolved | empty_patch | 6 |
| empty_patch | resolved | 3 |
| eval_error | empty_patch | 2 |
| resolved | eval_error | 1 |
| failed | agent_timeout | 1 |
| eval_error | failed | 1 |

Key observations:

- **22 of 32 identity-resolved instances broke under rename.** 15 produced patches that failed tests, 6 produced empty patches (agent gave up), 1 hit an eval error.
- **10 instances resolved under both conditions.** These are "easy" instances where obfuscation didn't prevent the agent from finding the fix.
- **10 instances resolved under rename but NOT identity.** This is noise from LLM non-determinism rather than obfuscation helping. The agent might take a different (luckier) trajectory when faced with unfamiliar names.
- **27 instances failed under both.** These are likely too hard for this model regardless of obfuscation.

## Impact breakdown

### Obfuscation hurts the agent in two ways:

1. **Agent produces wrong patches (resolved -> failed: 15).** The agent writes code using obfuscated names that don't match the test expectations, or the renamed symbols confuse its understanding of the codebase.

2. **Agent gives up entirely (resolved -> empty_patch: 6).** With 200 symbols renamed to `func_N`/`cls_N`, the agent can't navigate the codebase well enough to attempt a fix.

### Obfuscation error rate

14 out of 100 instances had rope errors during obfuscation (typically timeouts on large symbol graphs). These instances still ran with a partial rename — fewer symbols were renamed, but the obfuscation was not zero.

### Patch size

Median patch size is nearly identical (~1190 chars), suggesting the agent's verbosity isn't affected by obfuscation. The larger max and mean in the rename run come from a few instances where the agent produced unusually large patches (likely confused edits).

## Notes on methodology

- 57 instances were skipped via `docker_skip.yaml` (Docker OOM on older Django/Astropy envs).
- Cost tracking shows $0.00 because `gpt-5.4-nano` is not in litellm's price registry (`MSWEA_COST_TRACKING=ignore_errors`).
- The 10 "rename-resolved but identity-not" instances suggest non-trivial run-to-run variance. A proper comparison would average over multiple seeds, but API cost makes that impractical at this scale.
