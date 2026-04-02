"""Download HumanEval, shuffle with seed, save N samples as JSONL."""
from boilerplate_tools import setup_root

setup_root(n_up=1, verbose=True)

import json
from pathlib import Path

from datasets import load_dataset
from tqdm import tqdm

DATASET_NAME = "openai/openai_humaneval"
SPLIT = "test"
SEED = 42
N_SAMPLES = 164
OUTPUT_DIR = Path("artifacts/prepared")
OUTPUT_FILE = OUTPUT_DIR / "humaneval_164.jsonl"


def main() -> None:
    print(f"Loading {DATASET_NAME} (split={SPLIT})...")
    ds = load_dataset(DATASET_NAME, split=SPLIT)

    ds_filtered = ds.filter(
        lambda row: (
            bool(row.get("task_id"))
            and bool(row.get("prompt"))
            and bool(row.get("test"))
            and bool(row.get("entry_point"))
        ),
        desc="Filtering",
    )
    print(f"After filtering: {len(ds_filtered)} rows (from {len(ds)})")

    ds_shuffled = ds_filtered.shuffle(seed=SEED)
    ds_subset = ds_shuffled.select(range(min(N_SAMPLES, len(ds_shuffled))))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        for row in tqdm(ds_subset, desc="Writing JSONL", unit="row"):
            f.write(json.dumps(row) + "\n")

    print(f"Saved {len(ds_subset)} samples to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
