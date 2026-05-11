"""Run pipeline orchestration: load data, perturb, infer, store."""
import asyncio
import logging
from collections.abc import Mapping

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


def _remap_humaneval_entry_point_if_needed(
    request_metadata: dict,
    perturbation_stats: Mapping[str, object],
) -> dict:
    entry_point = request_metadata.get("entry_point")
    if not isinstance(entry_point, str):
        return request_metadata

    renamed_function_map = perturbation_stats.get("renamed_function_map")
    if not isinstance(renamed_function_map, Mapping):
        return request_metadata

    mapped = renamed_function_map.get(entry_point)
    if not isinstance(mapped, str):
        return request_metadata

    updated = dict(request_metadata)
    updated["original_entry_point"] = entry_point
    updated["entry_point"] = mapped
    return updated


def _build_request(sample: CodeTaskSample, task, perturbation, perturbation_name: str) -> tuple[ModelRequest, dict]:
    """Perturb code + build model request. Returns (request, perturbation_stats)."""
    pert_input = PerturbationInput(code=sample.code, sample_id=sample.sample_id)
    pert_result = perturbation.apply(pert_input)
    perturbation_stats = dict(pert_result.stats)
    request = task.build_request(sample, pert_result.perturbed_code)
    request_metadata = _remap_humaneval_entry_point_if_needed(
        request_metadata=dict(request.metadata),
        perturbation_stats=perturbation_stats,
    )
    request = ModelRequest(
        sample_id=request.sample_id,
        perturbation_name=perturbation_name,
        messages=request.messages,
        metadata=request_metadata,
    )
    return request, perturbation_stats


def _to_record(sample, task, request, response, perturbation_name, perturbation_stats) -> RunRecord:
    prediction = task.parse_prediction(sample, response)
    reference = task.build_reference(sample)
    record_metadata = dict(sample.metadata)
    record_metadata.update(dict(request.metadata))
    return RunRecord(
        sample_id=sample.sample_id,
        perturbation_name=perturbation_name,
        request_messages=request.messages,
        response_text=prediction,
        reference_text=reference,
        perturbation_stats=perturbation_stats,
        metadata=record_metadata,
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
    pbar = tqdm(total=len(samples), desc="Inference (async)", unit="sample")

    async def _process_one(sample: CodeTaskSample) -> RunRecord:
        request, stats = _build_request(sample, task, perturbation, perturbation_name)
        response = await runtime.ainvoke(request)  # semaphore is inside runtime
        record = _to_record(sample, task, request, response, perturbation_name, stats)
        store.append(record)
        pbar.update(1)
        return record

    records = await asyncio.gather(*(_process_one(s) for s in samples))
    pbar.close()
    return records


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
