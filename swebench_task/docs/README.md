# Docs index

## Reference

- [tutorial.md](reference/tutorial.md) - step-by-step walkthrough of the full pipeline (start here)
- [architecture.md](reference/architecture.md) - design decisions, deobfuscation strategy, logging approach

## Guides

- [prebuild_images.md](guides/prebuild_images.md) - out-of-band top-K Docker image prebuilder (kill the docker bottleneck)

## Reports

- [oom_audit.md](reports/oom_audit.md) - Docker OOM audit: env-image RAM scoring + skip list recommendations
- [obfuscation_fixes.md](reports/obfuscation_fixes.md) - rope syntax-error class of bugs and the `ignored_resources` fix
- [acceleration.md](reports/acceleration.md) - shipped and roadmap performance improvements (async pool, shallow clone, cache)
- [identity_vs_rename_mini_100.md](reports/identity_vs_rename_mini_100.md) - 100-instance `gpt-5.4-mini` comparison: identity vs. rope rename
- [identity_vs_rename_100.md](reports/identity_vs_rename_100.md) - same comparison on `gpt-5.4-nano`
- [run_100_analysis.md](reports/run_100_analysis.md) - error-mode breakdown on a 100-instance nano run
- [deobfuscation_e2e.md](reports/deobfuscation_e2e.md) - end-to-end verification of the deobfuscation protocol

## Dev

- [devlog.md](dev/devlog.md) - chronological build log with problems encountered and fixes
- [pr_description.md](dev/pr_description.md) - current PR summary, ready to paste into GitHub
