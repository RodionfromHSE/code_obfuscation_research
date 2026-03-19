"""Entry point for running evaluation on saved run artifacts."""
from boilerplate_tools import setup_root

setup_root(n_up=1, verbose=True)

import hydra
from omegaconf import DictConfig, OmegaConf

from code_obfuscation_research.pipelines.eval_pipeline import evaluate


@hydra.main(version_base=None, config_path="../configs", config_name="eval/default")
def main(cfg: DictConfig) -> None:
    print(OmegaConf.to_yaml(cfg))
    evaluate(cfg)


if __name__ == "__main__":
    main()
