"""Allow `python -m swebench_task` as the main entry point."""
import os
import warnings

os.environ.setdefault("MSWEA_SILENT_STARTUP", "1")
os.environ.setdefault("LITELLM_LOG", "ERROR")
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*chardet.*")
warnings.filterwarnings("ignore", message=".*RequestsDependencyWarning.*")

from pathlib import Path  # noqa: E402

import hydra  # noqa: E402
from omegaconf import DictConfig, OmegaConf  # noqa: E402

from swebench_task.prebuild.priority_yaml import load_priority_ids  # noqa: E402
from swebench_task.source.pipeline import run_swebench_pipeline  # noqa: E402
from swebench_task.utils.logging_config import configure_logging  # noqa: E402

_CONFIGS_DIR = str(Path(__file__).resolve().parent / "configs")


@hydra.main(version_base=None, config_path=_CONFIGS_DIR, config_name="default")
def main(cfg: DictConfig) -> None:
    log_dir = Path(cfg.paths.artifacts_dir) / "logs"
    configure_logging(log_dir, cfg.experiment_name)

    import logging
    logger = logging.getLogger("swebench_task")
    logger.debug("Config:\n%s", OmegaConf.to_yaml(cfg))

    obfuscation = hydra.utils.instantiate(cfg.repo_obfuscation)

    priority_path = cfg.get("priority_instances")
    priority_ids = load_priority_ids(Path(priority_path)) if priority_path else None
    if priority_ids:
        logger.info("Priority filter active: %d instance IDs (from %s)",
                    len(priority_ids), priority_path)

    artifacts_dir = Path(cfg.paths.artifacts_dir)
    run_swebench_pipeline(
        obfuscation=obfuscation,
        dataset_name=cfg.dataset.name,
        split=cfg.dataset.split,
        samples_limit=cfg.get("samples_limit"),
        shuffle_seed=cfg.dataset.get("shuffle_seed", 42),
        model_name=cfg.agent.model_name,
        max_turns=cfg.agent.max_turns,
        cost_limit=cfg.agent.cost_limit,
        timeout_seconds=cfg.agent.timeout_seconds,
        work_dir=artifacts_dir / "repos",
        output_dir=artifacts_dir / "runs",
        experiment_name=cfg.experiment_name,
        api_base=cfg.agent.get("api_base"),
        cost_tracking=cfg.agent.get("cost_tracking", "default"),
        cache_dir=Path(cfg.cache.dir) if cfg.cache.get("dir") else artifacts_dir / "cache",
        cache_enabled=cfg.cache.enabled,
        cache_read_only=cfg.cache.read_only,
        agent_concurrency=cfg.agent.get("concurrency", 1),
        eval_max_workers=cfg.eval.max_workers,
        eval_timeout=cfg.eval.timeout,
        shallow_clone=cfg.clone.shallow,
        priority_ids=priority_ids,
    )


if __name__ == "__main__":
    main()
