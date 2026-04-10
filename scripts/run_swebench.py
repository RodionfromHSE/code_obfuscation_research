"""Entry point for SWE-bench obfuscation experiments."""
import os
import warnings

os.environ.setdefault("MSWEA_SILENT_STARTUP", "1")
os.environ.setdefault("LITELLM_LOG", "ERROR")
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*chardet.*")
warnings.filterwarnings("ignore", message=".*RequestsDependencyWarning.*")

from boilerplate_tools import setup_root  # noqa: E402

setup_root(n_up=1, verbose=False)

from pathlib import Path  # noqa: E402

import hydra  # noqa: E402
from omegaconf import DictConfig, OmegaConf  # noqa: E402

from swe_task.logging_config import configure_logging  # noqa: E402
from swe_task.pipeline import run_swebench_pipeline  # noqa: E402


@hydra.main(version_base=None, config_path="../configs", config_name="swebench/default")
def main(cfg: DictConfig) -> None:
    log_dir = Path(cfg.paths.artifacts_dir) / "swebench" / "logs"
    configure_logging(log_dir, cfg.experiment_name)

    import logging
    logger = logging.getLogger(__name__)
    logger.debug("Config:\n%s", OmegaConf.to_yaml(cfg))

    obfuscation = hydra.utils.instantiate(cfg.repo_obfuscation)

    run_swebench_pipeline(
        obfuscation=obfuscation,
        dataset_name=cfg.dataset.name,
        split=cfg.dataset.split,
        samples_limit=cfg.get("samples_limit"),
        model_name=cfg.agent.model_name,
        max_turns=cfg.agent.max_turns,
        cost_limit=cfg.agent.cost_limit,
        timeout_seconds=cfg.agent.timeout_seconds,
        work_dir=Path(cfg.paths.artifacts_dir) / "swebench" / "repos",
        output_dir=Path(cfg.paths.artifacts_dir) / "swebench" / "runs",
        experiment_name=cfg.experiment_name,
    )


if __name__ == "__main__":
    main()
