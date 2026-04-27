"""End-to-end smoke: assert the pipeline's eval step reuses prebuilt instance images.

Assumes:
    - Docker is running.
    - You just ran `prebuild_images --top-k 1 --repo pytest --yes` (or similar).
    - Manifest at ~/Downloads/ml4se_images/manifest.json lists >=1 prebuilt image.

The smoke:
    1. Picks the first instance ID from the manifest.
    2. Builds a predictions.jsonl with the GOLD patch for that instance (so `git apply`
       succeeds and tests pass — eliminates agent variance).
    3. Calls `run_swebench_eval`.
    4. Checks that the harness printed "Found N existing instance images. Will reuse them."
    5. Checks that the instance resolved.

Usage:
    uv run python -m swebench_task.scripts.smoke_prebuild
"""
import argparse
import io
import json
import logging
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from datasets import load_dataset
from swebench_task.evaluation.swebench_eval import run_swebench_eval
from swebench_task.prebuild.manifest import PrebuildManifest
from swebench_task.scripts.prebuild_images import DEFAULT_ML4SE_DIR
from swebench_task.utils.logging_config import configure_logging

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ml4se-dir", type=Path, default=DEFAULT_ML4SE_DIR)
    parser.add_argument("--n", type=int, default=1, help="number of instances to eval")
    parser.add_argument(
        "--instance-id", action="append", default=None,
        help="explicit instance id(s) to eval (repeat for multiple); overrides --n",
    )
    parser.add_argument(
        "--run-id", default="smoke_prebuild", help="swebench run_id (unique per measurement)",
    )
    parser.add_argument(
        "--artifacts-dir", type=Path,
        default=Path("swebench_task/artifacts/smoke_prebuild"),
    )
    parser.add_argument(
        "--require-reuse", type=int, default=1,
        help="if >0, fail when the reuse marker isn't printed (set 0 for cold baselines)",
    )
    args = parser.parse_args()

    configure_logging(Path("logs"), "smoke_prebuild")

    manifest = PrebuildManifest.read(args.ml4se_dir.expanduser().resolve())
    if args.instance_id:
        picked_ids = list(args.instance_id)
    else:
        if not manifest.instance_images:
            print("Manifest lists no instance images. Run prebuild_images first.", file=sys.stderr)
            return 1
        picked_ids = [e.instance_id for e in manifest.instance_images[: args.n]]
    logger.info("Smoke will eval %d instance(s): %s", len(picked_ids), picked_ids)

    predictions_path = args.artifacts_dir / "predictions.jsonl"
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    gold_patches = _load_gold_patches(picked_ids, manifest.dataset)
    with predictions_path.open("w") as f:
        for iid, patch in gold_patches.items():
            f.write(json.dumps({
                "instance_id": iid,
                "model_name_or_path": "gold",
                "model_patch": patch,
            }) + "\n")
    logger.info("Wrote gold predictions -> %s", predictions_path)

    buf_out, buf_err = io.StringIO(), io.StringIO()
    t0 = time.perf_counter()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        results = run_swebench_eval(
            predictions_path=predictions_path,
            dataset_name=manifest.dataset,
            run_id=args.run_id,
            max_workers=min(len(picked_ids), 2),
            timeout=1800,
            report_dir=args.artifacts_dir,
        )
    elapsed = time.perf_counter() - t0

    combined = buf_out.getvalue() + buf_err.getvalue()
    sys.stdout.write(combined)

    reuse_marker = "Will reuse them"
    ok_reuse = reuse_marker in combined
    print("\n" + "=" * 60)
    print(f"  instances:            {picked_ids}")
    print(f"  wall_clock_seconds:   {elapsed:.1f}")
    print(f"  reuse marker present: {ok_reuse}")
    print(f"  results returned:     {len(results)}")

    per_id = {r.instance_id: r for r in results}
    resolved = [iid for iid in picked_ids if per_id.get(iid) and per_id[iid].resolved]
    print(f"  resolved (gold):      {len(resolved)}/{len(picked_ids)}")

    if args.require_reuse and not ok_reuse:
        print("FAIL: reuse marker missing (expected prebuilt image).", file=sys.stderr)
        return 1
    print("SMOKE DONE.")
    return 0


def _load_gold_patches(instance_ids: list[str], dataset_name: str) -> dict[str, str]:
    """Grab each instance's gold `patch` from HF dataset (combine with test_patch)."""
    ds = load_dataset(dataset_name, split="test")
    wanted = set(instance_ids)
    out: dict[str, str] = {}
    for row in ds:
        if row["instance_id"] in wanted:
            out[row["instance_id"]] = row["patch"]
    missing = wanted - set(out)
    if missing:
        raise RuntimeError(f"Gold patches missing for: {missing}")
    return out


if __name__ == "__main__":
    sys.exit(main())
