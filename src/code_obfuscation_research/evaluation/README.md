# evaluation/

Binary correctness evaluation using DeepEval's GEval with `strict_mode=True`.

## How it works

The eval pipeline reads saved `RunRecord` JSONL files (never calls the task model again) and builds eval cases:

- **input**: the user message from the prompt (question + code context)
- **actual_output**: the model's prediction
- **expected_output**: the reference answer from the dataset

A judge model (`gpt-5.4-mini-2026-03-17` by default) scores each case as **0 (incorrect) or 1 (correct)** based on configurable evaluation steps.

The judge **does not** see the original private code -- only the question, the model's answer, and the expected answer. This prevents the evaluation itself from leaking private information.

## Output

`CorrectnessResult` per sample: `sample_id`, `perturbation_name`, `is_correct` (bool), `score` (0.0 or 1.0), and `reason` (judge's explanation).

The eval pipeline prints a summary grouped by perturbation:
```
[noop]           n=100 correct=87/100 (87%) errors=0
[rename_symbols] n=100 correct=71/100 (71%) errors=2
```
