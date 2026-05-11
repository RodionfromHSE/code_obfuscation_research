# Docker eval: how it works and how to make it 3x faster

## How the eval phase works

SWE-bench's eval harness uses a three-layer Docker image hierarchy:

```
sweb.base         (python + core deps, shared by everything)
  └── sweb.env.*  (repo + version deps, e.g. "django 4.0 + python 3.9")
        └── sweb.eval.*  (per-instance: git clone at base_commit + pip install)
```

When the pipeline calls `run_swebench_eval(predictions_path, ...)`, the
harness does this **for each instance**:

1. **Check if `sweb.eval.<instance_id>:latest` exists in Docker.**
   - If yes &rarr; reuse it, skip to step 4.
   - If no &rarr; continue to step 2.
2. **Build the env image** (`sweb.env.<repo>__<version>`) if it doesn't exist
   yet. This is conda-solve + pip-install of the repo's full dependency tree.
   Typically 2-10 min, but cached across instances of the same (repo, version).
3. **Build the instance image** on top of the env image: clone the repo at
   `base_commit`, install its editable package. Typically 2-5 min.
4. **Run a container** from the instance image: apply the model's patch,
   execute the test suite, collect pass/fail. Typically 30-120 s.

### What happens at teardown

After the run, the harness calls `should_remove()` for every image it touched.
The logic (simplified) is:

```python
def should_remove(image_name, cache_level, clean, prior_images):
    existed_before = image_name in prior_images   # <-- key flag
    if image_name.startswith("sweb.eval"):
        if cache_level in {"none", "base", "env"}:
            return clean or not existed_before
    ...
```

Our pipeline calls the harness with `cache_level="env"` and `clean=False`.
This means:

| Image | `existed_before` | Removed? |
|---|---|---|
| `sweb.env.*` | (any) | No (level is "env", env images kept) |
| `sweb.eval.*` built during this run | `False` | **Yes** (not existed before) |
| `sweb.eval.*` that was prebuilt | `True` | **No** (existed before the run) |

So: **env images survive across runs, but instance images built during a run
are deleted at teardown.** Prebuilt instance images survive because
`existed_before=True`.

### Does one instance's image get reused by another?

No. Each instance has a unique `sweb.eval.<instance_id>` image (different
`base_commit`, different installed state). Instance images are never shared.

What IS shared is the **env image** underneath: all 18 instances of
`django/django v4.0` share a single `sweb.env.django__django-4.0` image.
That env image is built once (on the first instance that needs it) and cached.

## Where the time goes (100 instances, no prebuild)

Rough breakdown with `eval.max_workers=2`:

| Component | Per instance | 100 instances / 2 workers |
|---|---|---|
| Env image build (cold) | 2-10 min | ~30 min total (39 unique envs, but cached across instances) |
| Instance image build | 2-5 min | ~150 min total (100 builds, 2 in parallel) |
| Test execution | 0.5-2 min | ~50 min total |
| **Total eval phase** | | **~230 min (~3.8 hours)** |

The instance image build completely dominates. On a re-run, env images are
cached so the 30-min chunk vanishes, but you still rebuild all 100 instance
images every time (~200 min).

## Prebuilding: how to get 80+ instances covered

### Your 100 instances break down like this

| top-K buckets | Instances covered | Cumulative disk |
|---|---|---|
| 1 (django 4.0) | 18 | ~24 GB |
| 4 (all django) | 46 | ~65 GB |
| 8 (+sympy, matplotlib, sphinx) | 59 | ~93 GB |
| 18 (+remaining 2-instance buckets) | 79 | ~144 GB |
| 29 (all 39 buckets with >= 1) | 90 | ~178 GB |
| 39 (all buckets) | 100 | ~220 GB |

### The realistic plan: top-8 for ~60% coverage, top-18 for ~80%

Going all-39 costs ~220 GB of Docker disk, which exceeds most laptop VMs.
But you can hit 80 instances with top-18 (~144 GB) or 90 with top-29 (~178 GB).

**The sweet spot** depends on your Docker Desktop VM disk allocation. Check it:

```bash
docker system df
```

Then pick a `--max-total-gb` that leaves ~30 GB headroom.

### Step-by-step

**1. Dry run — see the plan, no docker calls:**

```bash
uv run python -m swebench_task.scripts.prebuild_images \
    --top-k 18 --max-total-gb 150 --dry-run
```

This prints a table of which buckets are selected, how many instances, and
estimated disk. It also writes `configs/priority_instances.yaml` (harmless,
just a YAML listing the covered instance IDs).

**2. Build for real:**

```bash
uv run python -m swebench_task.scripts.prebuild_images \
    --top-k 18 --max-total-gb 150 --workers 2 --yes
```

- `--workers 2`: two parallel Docker builds. Raise to 4 if you have 32+ GB
  RAM; lower to 1 if you see OOM kills.
- Takes ~60-90 min the first time (dominated by conda-solve for
  scipy/matplotlib envs).
- After it finishes, run `docker images | grep sweb.eval | wc -l` to confirm
  the count matches.

**3. Run the pipeline — all 100 instances, prebuilt ones are fast:**

```bash
uv run python -m swebench_task --config-name=exp_identity_gpt_mini
```

No extra flags needed. The harness auto-detects existing `sweb.eval.*` images
and reuses them.

**4. Cleanup when done with all experiments:**

```bash
bash ~/Downloads/ml4se_images/cleanup.sh
```

### Expected speedup

With 80/100 instances prebuilt:

| Component | No prebuild | With 80 prebuilt |
|---|---|---|
| Instance image builds | 100 × ~3 min = ~300 min | 20 × ~3 min = ~60 min |
| Test execution | 100 × ~1 min = ~100 min | 100 × ~1 min = ~100 min |
| Env image builds | ~30 min (cached) | ~10 min (fewer unique cold envs) |
| **Total (2 workers)** | **~215 min** | **~85 min** |
| **Speedup** | 1x | **~2.5x** |

With 90/100 prebuilt (top-29, ~178 GB) the speedup approaches **~3x**.

The last 10 un-prebuilt instances are from singleton buckets (1 instance each).
Each needs a unique env build, so they're disproportionately expensive per
instance. Prebuilding them too costs ~40 GB more disk for only ~10 min of
wall-clock savings — diminishing returns.

## Constraints and gotchas

### Disk

Docker Desktop's VM has a fixed disk allocation (default 64 GB on macOS).
You need to increase it:

**Docker Desktop &rarr; Settings &rarr; Resources &rarr; Disk image size**

Set it to at least `prebuild GB + 30 GB` headroom. For 80 prebuilt instances
(~144 GB), you want the VM disk at ~180 GB.

If you forget this step, builds will fail mid-way with cryptic "no space left
on device" errors inside the container.

### RAM

Each parallel Docker build peaks at 2-4 GB. With `--workers 2`, budget 8 GB
for Docker. The heavy envs (scikit-learn, astropy) can spike to 6 GB during
conda-solve — that's why those are in `docker_skip.yaml`.

### Build time

First prebuild is slow (~60-90 min) because every env is cold. Subsequent
prebuilds (after adding more buckets) only build the new ones — Docker layer
caching handles the rest.

### Instance images are NOT portable

`sweb.eval.*` images live inside Docker Desktop's VM. You can't `docker save`
them to an external drive and reload on another machine without significant
effort. They're tied to the Docker daemon that built them.

### 100 samples? Yes, absolutely

Prebuilding does NOT change which instances the pipeline runs. It only
pre-populates Docker's image cache. The pipeline always runs all
`samples_limit` instances regardless. Un-prebuilt instances just build their
image on-the-fly (slower but correct).

```bash
# this still runs exactly 100 instances
uv run python -m swebench_task --config-name=exp_identity_gpt_mini
# samples_limit: 100  (set in the config)
```

The only thing `priority_instances=` does is RESTRICT the pipeline to only
prebuilt IDs. Don't use it if you want all 100.

## Quick reference

```bash
# check docker disk
docker system df

# dry-run: plan for 80+ coverage
uv run python -m swebench_task.scripts.prebuild_images \
    --top-k 18 --max-total-gb 150 --dry-run

# build (takes ~60-90 min first time)
uv run python -m swebench_task.scripts.prebuild_images \
    --top-k 18 --max-total-gb 150 --workers 2 --yes

# verify
docker images | grep sweb.eval | wc -l   # should show ~79

# run pipeline (all 100 instances, 80 are fast)
uv run python -m swebench_task --config-name=exp_identity_gpt_mini

# cleanup
bash ~/Downloads/ml4se_images/cleanup.sh
```
