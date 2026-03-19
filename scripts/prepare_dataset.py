"""Download CodeQA, shuffle with seed, save N samples as JSONL."""
from boilerplate_tools import setup_root

setup_root(n_up=1, verbose=True)

import json
from pathlib import Path

from datasets import load_dataset
from tqdm import tqdm

DATASET_NAME = "vm2825/CodeQA-dataset"
SPLIT = "train"
SEED = 42
N_SAMPLES = 200
OUTPUT_DIR = Path("artifacts/prepared")
OUTPUT_FILE = OUTPUT_DIR / "codeqa_200.jsonl"


def main() -> None:
    print(f"Loading {DATASET_NAME} (split={SPLIT})...")
    ds = load_dataset(DATASET_NAME, split=SPLIT)

    ds_filtered = ds.filter(
        lambda row: bool(row.get("input_code")) and bool(row.get("Instruction")),
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
