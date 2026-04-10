# Stages 4-6: Manual Testing Guide

All code for stages 4-6 is implemented. These stages require live API calls, Docker, and
real SWE-bench instances, so they need manual testing. Follow these steps in order.

## Stage 4: Agent wrapper (`swe_task/agent/runner.py`)

### Test 4.1: Verify mini-swe-agent can instantiate with your model

```bash
uv run python -c "
from minisweagent.models.litellm_model import LitellmModel
model = LitellmModel(model_name='openai/gpt-5.4-nano-2026-03-17')
print('Model instantiated OK')
"
```

Expected: no error. If API key issues, set `OPENAI_API_KEY` env var.

### Test 4.2: Run agent on a trivial local repo

```bash
# create a tiny test repo
mkdir -p /tmp/test_swe_repo && cd /tmp/test_swe_repo
git init
echo 'def greet(name):\n    return f"hello {name}"' > main.py
git add . && git commit -m "init"

# run agent
uv run python -c "
from swe_task.agent.runner import run_agent
from pathlib import Path

result = run_agent(
    repo_dir=Path('/tmp/test_swe_repo'),
    problem_statement='Add a docstring to the greet function in main.py',
    instance_id='test_trivial',
    model_name='openai/gpt-5.4-nano-2026-03-17',
    max_turns=10,
    timeout_seconds=120,
)
print(f'timed_out={result.timed_out}')
print(f'error={result.error}')
print(f'patch length={len(result.model_patch)}')
print(f'--- patch ---')
print(result.model_patch[:500])
"
```

**Check**: agent should produce a non-empty patch. It should finish in <2 min.

### Test 4.3: Verify timeout works

```bash
uv run python -c "
from swe_task.agent.runner import run_agent
from pathlib import Path

result = run_agent(
    repo_dir=Path('/tmp/test_swe_repo'),
    problem_statement='Rewrite the entire codebase to use async/await with full test suite',
    instance_id='test_timeout',
    model_name='openai/gpt-5.4-nano-2026-03-17',
    max_turns=5,
    timeout_seconds=30,
)
print(f'timed_out={result.timed_out}')
print(f'error={result.error}')
"
```

**Check**: should return `timed_out=True` if agent doesn't finish in 30s.

---

## Stage 5: SWE-bench eval wrapper (`swe_task/evaluation/swebench_eval.py`)

### Test 5.1: Write a predictions file with gold patch

```bash
uv run python -c "
from datasets import load_dataset
from swe_task.evaluation.swebench_eval import save_predictions
from swe_task.agent.runner import AgentRunResult
from pathlib import Path

ds = load_dataset('SWE-bench/SWE-bench_Verified', split='test')
instance = ds[0]
print(f'Instance: {instance[\"instance_id\"]}')

# use gold patch as prediction
result = AgentRunResult(
    instance_id=instance['instance_id'],
    model_patch=instance['patch'],
)

path = save_predictions(
    [result],
    Path('artifacts/swebench/test_eval/predictions.jsonl'),
    'gold_patch',
)
print(f'Saved to {path}')
"
```

### Test 5.2: Run swebench eval on gold patch (requires Docker)

```bash
uv run python -c "
from swe_task.evaluation.swebench_eval import run_swebench_eval
from pathlib import Path

results = run_swebench_eval(
    predictions_path=Path('artifacts/swebench/test_eval/predictions.jsonl'),
    dataset_name='SWE-bench/SWE-bench_Verified',
    max_workers=1,
    run_id='test_gold',
)
for r in results:
    print(f'{r.instance_id}: resolved={r.resolved}')
"
```

**Check**: gold patch should resolve as `True`. If Docker issues, check `docker info`.

---

## Stage 6: End-to-end pipeline

### Test 6.1: Single instance, identity (no obfuscation)

```bash
uv run python scripts/run_swebench.py \
    samples_limit=1 \
    experiment_name=test_identity \
    agent.timeout_seconds=300
```

**Check**:
- Instance report saved to `artifacts/swebench/runs/test_identity/instance_reports/`
- Summary saved to `artifacts/swebench/runs/test_identity/summary.json`
- Look at the instance report JSON: status should be one of: resolved, failed, agent_error, agent_timeout

### Test 6.2: Single instance, rope_rename obfuscation

```bash
uv run python scripts/run_swebench.py \
    repo_obfuscation=rope_rename \
    samples_limit=1 \
    experiment_name=test_rope_rename \
    agent.timeout_seconds=300
```

**Check**:
- Instance report should show `symbols_renamed > 0`
- Compare resolved status with Test 6.1

### Test 6.3: Check agent reasoning

Open the instance report JSON. Key things to verify:
1. `obfuscation.symbols_renamed` > 0 (rope_rename), == 0 (identity)
2. `obfuscation.errors` is empty or has only timeout/skip items (no crashes)
3. `agent.model_patch` is non-empty (agent produced output)
4. `agent.timed_out` is False
5. `agent.error` is None

---

## Cost estimate

| Test | Instances | Est. cost |
|------|-----------|-----------|
| 4.2  | 1 trivial | ~$0.05    |
| 4.3  | 1 trivial | ~$0.02    |
| 6.1  | 1 real    | ~$0.50-2  |
| 6.2  | 1 real    | ~$0.50-2  |
| **Total dev testing** | | **~$1-4** |

## Guardrails recap

| Concern | Guard |
|---------|-------|
| Agent hangs | `timeout_seconds` (default 1200s, use 300 for testing) |
| Agent burns money | `max_turns=50` limits API calls |
| Rope hangs on big symbol | `per_symbol_timeout=30`, `max_symbols=200` |
| Docker not running | `swebench_eval` returns error result, doesn't crash |
| Obfuscation breaks code | Expected and measured -- that IS the experiment data |
