"""Print a compact summary table for evaluation JSONL artifacts."""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from boilerplate_tools import setup_root

setup_root(n_up=1, verbose=False)


def _iter_result_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        with open(path) as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    row["_eval_file"] = path.name
                    rows.append(row)
    return rows


def _summarize(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["_eval_file"], row.get("perturbation_name", ""))].append(row)

    summary = []
    for (eval_file, perturbation), group in sorted(grouped.items()):
        n = len(group)
        correct = sum(1 for row in group if row.get("is_correct") is True)
        errors = sum(1 for row in group if row.get("score") is None)
        summary.append(
            {
                "eval_file": eval_file,
                "perturbation": perturbation,
                "n": n,
                "correct": correct,
                "accuracy": correct / n if n else 0.0,
                "errors": errors,
            }
        )
    return summary


def _print_markdown(summary: list[dict]) -> None:
    print("| eval_file | perturbation | n | correct | accuracy | errors |")
    print("| --- | --- | ---: | ---: | ---: | ---: |")
    for row in summary:
        print(
            "| {eval_file} | {perturbation} | {n} | {correct} | {accuracy:.1%} | {errors} |".format(**row)
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path, help="Evaluation JSONL files or directories")
    args = parser.parse_args()
    inputs = args.paths or [Path("artifacts/evals")]
    files: list[Path] = []
    for path in inputs:
        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))
        elif path.exists():
            files.append(path)

    if not files:
        raise SystemExit("No evaluation JSONL files found.")

    _print_markdown(_summarize(_iter_result_rows(files)))


if __name__ == "__main__":
    main()
