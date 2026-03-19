"""Run pipeline orchestration: load data, perturb, infer, store."""
import asyncio
import logging

from hydra.utils import instantiate
from omegaconf import DictConfig
from tqdm import tqdm

from code_obfuscation_research.domain import (
    CodeTaskSample,
    ModelRequest,
    PerturbationInput,
    RunRecord,
)
from code_obfuscation_research.runtime.cache import setup_cache
from code_obfuscation_research.runtime.llm_runtime import LLMRuntime
from code_obfuscation_research.runtime.store import RunStore

logger = logging.getLogger(__name__)


def _build_request(sample: CodeTaskSample, task, perturbation, perturbation_name: str) -> tuple[ModelRequest, dict]:
    """Perturb code + build model request. Returns (request, perturbation_stats)."""
    pert_input = PerturbationInput(code=sample.code, sample_id=sample.sample_id)
    pert_result = perturbation.apply(pert_input)
    request = task.build_request(sample, pert_result.perturbed_code)
    request = ModelRequest(
        sample_id=request.sample_id,
        perturbation_name=perturbation_name,
        messages=request.messages,
        metadata=request.metadata,
    )
    return request, dict(pert_result.stats)


def _to_record(sample, task, request, response, perturbation_name, perturbation_stats) -> RunRecord:
    prediction = task.parse_prediction(sample, response)
    reference = task.build_reference(sample)
    return RunRecord(
        sample_id=sample.sample_id,
        perturbation_name=perturbation_name,
        request_messages=request.messages,
        response_text=prediction,
        reference_text=reference,
        perturbation_stats=perturbation_stats,
    )


def _run_sync(samples, task, perturbation, runtime, store, perturbation_name) -> list[RunRecord]:
    records = []
    for sample in tqdm(samples, desc="Inference", unit="sample"):
        request, stats = _build_request(sample, task, perturbation, perturbation_name)
        response = runtime.invoke(request)
        record = _to_record(sample, task, request, response, perturbation_name, stats)
        store.append(record)
        records.append(record)
    return records


async def _run_async(samples, task, perturbation, runtime, store, perturbation_name) -> list[RunRecord]:
    async def _process_one(sample: CodeTaskSample) -> RunRecord:
        request, stats = _build_request(sample, task, perturbation, perturbation_name)
        response = await runtime.ainvoke(request)  # semaphore is inside runtime
        record = _to_record(sample, task, request, response, perturbation_name, stats)
        store.append(record)
        return record

    return await asyncio.gather(*(_process_one(s) for s in samples))


def run(cfg: DictConfig) -> list[RunRecord]:
    """Execute an inference experiment."""
    setup_cache(cfg.runtime.cache_db)

    dataset_adapter = instantiate(cfg.dataset)
    task = instantiate(cfg.task)
    perturbation = instantiate(cfg.perturbation)
    model = instantiate(cfg.model)

    runtime = LLMRuntime(
        model=model,
        max_parse_retries=cfg.runtime.max_parse_retries,
        max_concurrent=cfg.runtime.get("max_concurrent", 5),
    )

    samples = dataset_adapter.load_split(limit=cfg.get("samples_limit"))
    perturbation_name = perturbation.name

    store = RunStore(
        output_dir=cfg.paths.runs_dir,
        experiment_name=cfg.experiment_name,
        perturbation_name=perturbation_name,
    )

    logger.info(
        "Starting run: %d samples, perturbation=%s, model=%s",
        len(samples),
        perturbation_name,
        cfg.model.model_name,
    )
    print(f"Starting: {len(samples)} samples, perturbation={perturbation_name}, model={cfg.model.model_name}")

    if cfg.runtime.async_mode:
        records = asyncio.run(_run_async(samples, task, perturbation, runtime, store, perturbation_name))
    else:
        records = _run_sync(samples, task, perturbation, runtime, store, perturbation_name)

    logger.info("Run complete: %d records saved to %s", len(records), store.path)
    print(f"Run complete: {len(records)} records -> {store.path}")
    return records
