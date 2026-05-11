#!/usr/bin/env bash
# Run MultiPL-E HumanEval-JS for one or more perturbations, score everything,
# and print a per-task comparison vs. the first perturbation (treated as baseline).
#
# Usage:
#   scripts/run_multipl_e_js_comparison.sh                       # all 161 tasks, noop vs rename_symbols_js
#   scripts/run_multipl_e_js_comparison.sh 20                    # first 20 tasks
#   scripts/run_multipl_e_js_comparison.sh 50 noop rename_symbols_js rename_symbols_js_params_only
#   FORCE=1 scripts/run_multipl_e_js_comparison.sh 20            # re-run inference even if cached
set -euo pipefail

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY is not set." >&2
  echo "       export OPENAI_API_KEY=sk-... before running." >&2
  exit 1
fi

LIMIT="${1:-null}"; shift || true
if [ "$#" -eq 0 ]; then
  PERTURBATIONS=(noop rename_symbols_js)
else
  PERTURBATIONS=("$@")
fi
BASELINE="${PERTURBATIONS[0]}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS_DIR="$REPO_ROOT/artifacts/runs"
EVAL_FILE="$REPO_ROOT/artifacts/evals/multipl_e_humaneval_js_eval_results.jsonl"

echo ">>> MultiPL-E HumanEval-JS comparison"
echo "    samples_limit: $LIMIT"
echo "    perturbations: ${PERTURBATIONS[*]}"
echo "    baseline:      $BASELINE"
echo

for pert in "${PERTURBATIONS[@]}"; do
  run_file="$RUNS_DIR/multipl_e_humaneval_js_run_${pert}.jsonl"
  if [ -f "$run_file" ] && [ -z "${FORCE:-}" ]; then
    echo "--- $pert  (cached: $run_file — set FORCE=1 to re-run inference) ---"
    continue
  fi
  echo "--- $pert  (running inference) ---"
  uv run python "$REPO_ROOT/scripts/run_experiment.py" \
    --config-name=run/multipl_e_humaneval_js \
    perturbation="$pert" \
    samples_limit="$LIMIT"
done

echo
echo ">>> Scoring all run files in $RUNS_DIR..."
uv run python "$REPO_ROOT/scripts/run_evaluation.py" \
  --config-name=eval/multipl_e_humaneval_js

echo
echo ">>> Per-task comparison (baseline=$BASELINE):"
for pert in "${PERTURBATIONS[@]}"; do
  if [ "$pert" = "$BASELINE" ]; then continue; fi
  uv run python "$REPO_ROOT/scripts/compare_perturbations.py" \
    --eval-file "$EVAL_FILE" \
    --baseline "$BASELINE" \
    --compared "$pert"
done
