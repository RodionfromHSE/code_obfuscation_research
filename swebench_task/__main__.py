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
        work_dir=Path(cfg.paths.artifacts_dir) / "repos",
        output_dir=Path(cfg.paths.artifacts_dir) / "runs",
        experiment_name=cfg.experiment_name,
    )


if __name__ == "__main__":
    main()
