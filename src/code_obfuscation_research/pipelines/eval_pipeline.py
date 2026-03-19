"""Evaluation pipeline: load run artifacts, run binary correctness, save results."""
import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from deepeval.metrics import GEval
from omegaconf import DictConfig, OmegaConf
from tqdm import tqdm

from code_obfuscation_research.domain import EvalCase, RunRecord
from code_obfuscation_research.evaluation.deepeval_runner import (
    CorrectnessResult,
    arun_correctness,
    build_correctness_metric,
    run_correctness,
)
from code_obfuscation_research.runtime.store import RunStore

logger = logging.getLogger(__name__)


def _records_to_eval_cases(records: list[RunRecord]) -> list[EvalCase]:
    cases = []
    for r in records:
        question = ""
        for msg in r.request_messages:
            if msg["role"] == "user":
                question = msg["content"]
                break
        cases.append(
            EvalCase(
                sample_id=r.sample_id,
                input_text=question,
                actual_output=r.response_text,
                expected_output=r.reference_text,
                perturbation_name=r.perturbation_name,
            )
        )
    return cases


def _find_run_files(runs_dir: str | Path) -> list[Path]:
    runs_path = Path(runs_dir)
    if not runs_path.exists():
        return []
    return sorted(runs_path.glob("*.jsonl"))


def _save_results(output_dir: Path, experiment_name: str, results: list[CorrectnessResult]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{experiment_name}_results.jsonl"
    with open(out_path, "w") as f:
        for r in results:
            f.write(json.dumps(asdict(r)) + "\n")
    logger.info("Saved %d eval results to %s", len(results), out_path)
    return out_path


def evaluate(cfg: DictConfig) -> None:
    """Run evaluation on saved run artifacts."""
    runs_dir = cfg.run_artifacts_path
    evals_dir = cfg.paths.evals_dir
    experiment_name = cfg.experiment_name

    run_files = _find_run_files(runs_dir)
    if not run_files:
        logger.warning("No run files found in %s", runs_dir)
        return

    all_records: list[RunRecord] = []
    for f in run_files:
        all_records.extend(RunStore.load_from_path(f))

    limit = cfg.get("samples_limit")
    if limit:
        all_records = all_records[:limit]

    logger.info("Evaluating %d records from %d files", len(all_records), len(run_files))
    print(f"Evaluating: {len(all_records)} records from {len(run_files)} files")
    cases = _records_to_eval_cases(all_records)

    evaluator_cfg = cfg.evaluator
    eval_steps = OmegaConf.to_container(evaluator_cfg.evaluation_steps, resolve=True)
    judge_model = cfg.judge_model.model_name
    threshold = evaluator_cfg.get("threshold", 0.5)

    def metric_factory() -> GEval:
        return build_correctness_metric(
            evaluation_steps=eval_steps,
            threshold=threshold,
            model=judge_model,
        )

    max_concurrent = cfg.runtime.get("max_concurrent", 5)

    if cfg.runtime.async_mode:
        results = asyncio.run(_run_async(metric_factory, cases, max_concurrent))
    else:
        metric = metric_factory()
        results = [run_correctness(metric, c) for c in tqdm(cases, desc="Evaluating", unit="case")]

    _save_results(Path(evals_dir), experiment_name, results)
    _print_summary(results)


async def _run_async(
    metric_factory: Callable[[], GEval], cases: list[EvalCase], max_concurrent: int,
) -> list[CorrectnessResult]:
    sem = asyncio.Semaphore(max_concurrent)
    pbar = tqdm(total=len(cases), desc="Evaluating (async)", unit="case")

    async def _limited(case: EvalCase) -> CorrectnessResult:
        async with sem:
            metric = metric_factory()  # fresh metric per call — GEval is stateful
            result = await arun_correctness(metric, case)
        pbar.update(1)
        return result

    results = await asyncio.gather(*(_limited(c) for c in cases))
    pbar.close()
    return results


def _print_summary(results: list[CorrectnessResult]) -> None:
    by_pert: dict[str, list[CorrectnessResult]] = {}
    for r in results:
        by_pert.setdefault(r.perturbation_name, []).append(r)

    print("\n=== Evaluation Summary ===")
    for pert_name, group in sorted(by_pert.items()):
        n = len(group)
        correct = sum(1 for r in group if r.is_correct)
        errors = sum(1 for r in group if r.score is None)
        print(f"  [{pert_name}] n={n} correct={correct}/{n} ({correct/n:.0%}) errors={errors}")
    print()
