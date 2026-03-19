"""Entry point for running inference experiments."""
from boilerplate_tools import setup_root

setup_root(n_up=1, verbose=False)

import logging

import hydra
from hydra.core.hydra_config import HydraConfig
from omegaconf import DictConfig, OmegaConf

from code_obfuscation_research.pipelines.run_pipeline import run
from code_obfuscation_research.runtime.logging import configure_logging

logger = logging.getLogger(__name__)


@hydra.main(version_base=None, config_path="../configs", config_name="run/default")
def main(cfg: DictConfig) -> None:
    output_dir = HydraConfig.get().runtime.output_dir
    configure_logging(log_file=f"{output_dir}/run.log")
    logger.debug("Resolved config:\n%s", OmegaConf.to_yaml(cfg))
    run(cfg)


if __name__ == "__main__":
    main()
