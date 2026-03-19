"""Entry point for running inference experiments."""
from boilerplate_tools import setup_root

setup_root(n_up=1, verbose=True)

import hydra
from omegaconf import DictConfig, OmegaConf

from code_obfuscation_research.pipelines.run_pipeline import run


@hydra.main(version_base=None, config_path="../configs", config_name="run/default")
def main(cfg: DictConfig) -> None:
    print(OmegaConf.to_yaml(cfg))
    run(cfg)


if __name__ == "__main__":
    main()
