"""Freeze the current (dataset x skip list x shuffle seed) ordering into a YAML file.

Why: the dataset order depends on the skip list — every change to docker_skip.yaml
reshuffles the stream. Freezing the ordering once makes future skip-list edits
"subtractive only": expanding the skip list removes instances without reshuffling
the survivors.

Usage:
    uv run python -m swebench_task.scripts.freeze_instance_order
    # -> writes swebench_task/configs/instance_order.yaml with all usable IDs
"""
import argparse
import logging
import random
from pathlib import Path

import yaml
from datasets import load_dataset
from swebench_task.source.dataset import load_skip_list
from swebench_task.utils.logging_config import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="SWE-bench/SWE-bench_Verified")
    parser.add_argument("--split", default="test")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "configs" / "instance_order.yaml",
    )
    args = parser.parse_args()

    configure_logging(Path("logs"), "freeze_instance_order")

    skip_ids = load_skip_list()
    ds = load_dataset(args.dataset, split=args.split)
    all_ids = [row["instance_id"] for row in ds]
    random.Random(args.seed).shuffle(all_ids)
    ordered = [iid for iid in all_ids if iid not in skip_ids]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(
        {
            "generated_from": {
                "dataset": args.dataset,
                "split": args.split,
                "seed": args.seed,
                "n_total": len(all_ids),
                "n_skipped": len(all_ids) - len(ordered),
                "n_usable": len(ordered),
            },
            "ordered_instance_ids": ordered,
        },
        sort_keys=False,
    ))
    logger.info("Wrote %d instance IDs to %s (skipped %d)", len(ordered), args.output, len(all_ids) - len(ordered))


if __name__ == "__main__":
    main()
