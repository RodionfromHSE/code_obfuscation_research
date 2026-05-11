"""Compare two perturbations from the same eval results file.

Reads a `<experiment>_results.jsonl` produced by `scripts/run_evaluation.py`
and prints per-perturbation pass rates plus the list of tasks that regressed
(baseline pass -> compared fail) and recovered (baseline fail -> compared pass).

Usage:
    python scripts/compare_perturbations.py \\
        --eval-file artifacts/evals/multipl_e_humaneval_js_eval_results.jsonl \\
        --baseline noop \\
        --compared rename_symbols_js
"""
import argparse
import json
import sys
from pathlib import Path


def load_results(eval_file: Path) -> dict[str, dict[str, dict]]:
    """Return {perturbation_name: {sample_id: result_dict}}."""
    by_pert: dict[str, dict[str, dict]] = {}
    with open(eval_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            by_pert.setdefault(r["perturbation_name"], {})[r["sample_id"]] = r
    return by_pert


def _truncate(text: str, limit: int = 100) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def compare(eval_file: Path, baseline: str, compared: str) -> int:
    by_pert = load_results(eval_file)

    if baseline not in by_pert:
        print(f"ERROR: no '{baseline}' rows in {eval_file}.")
        print(f"Available perturbations: {sorted(by_pert)}")
        return 1
    if compared not in by_pert:
        print(f"ERROR: no '{compared}' rows in {eval_file}.")
        print(f"Available perturbations: {sorted(by_pert)}")
        return 1

    b_rows = by_pert[baseline]
    c_rows = by_pert[compared]

    common = sorted(set(b_rows) & set(c_rows))
    only_b = sorted(set(b_rows) - set(c_rows))
    only_c = sorted(set(c_rows) - set(b_rows))

    if not common:
        print(f"ERROR: no overlapping sample_ids between '{baseline}' and '{compared}'.")
        return 1

    b_pass = sum(1 for s in common if b_rows[s]["is_correct"])
    c_pass = sum(1 for s in common if c_rows[s]["is_correct"])
    n = len(common)

    regressions = [s for s in common if b_rows[s]["is_correct"] and not c_rows[s]["is_correct"]]
    recoveries = [s for s in common if not b_rows[s]["is_correct"] and c_rows[s]["is_correct"]]
    both_pass = sum(1 for s in common if b_rows[s]["is_correct"] and c_rows[s]["is_correct"])
    both_fail = sum(1 for s in common if not b_rows[s]["is_correct"] and not c_rows[s]["is_correct"])

    print(f"\n=== {baseline} vs {compared}  (n={n} common samples) ===")
    print(f"  {baseline:35s}  pass: {b_pass:>3d}/{n} ({b_pass/n:.0%})")
    print(f"  {compared:35s}  pass: {c_pass:>3d}/{n} ({c_pass/n:.0%})")
    delta = c_pass - b_pass
    delta_pct = (c_pass - b_pass) / n
    print(f"  delta:                              {delta:+d} ({delta_pct:+.1%})")
    print()
    print(f"  regressions (baseline pass -> compared fail): {len(regressions)}")
    for s in regressions:
        reason = _truncate(c_rows[s].get("reason", ""))
        print(f"    - {s}: {reason}")
    print()
    print(f"  recoveries (baseline fail -> compared pass): {len(recoveries)}")
    for s in recoveries:
        print(f"    - {s}")
    print()
    print(f"  both pass: {both_pass}    both fail: {both_fail}")
    if only_b:
        print(f"  only in {baseline}: {len(only_b)} (probably different samples_limit)")
    if only_c:
        print(f"  only in {compared}: {len(only_c)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-file", required=True, type=Path)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--compared", required=True)
    args = parser.parse_args()

    if not args.eval_file.exists():
        print(f"ERROR: {args.eval_file} does not exist. Run scripts/run_evaluation.py first.")
        return 1

    return compare(args.eval_file, args.baseline, args.compared)


if __name__ == "__main__":
    sys.exit(main())
