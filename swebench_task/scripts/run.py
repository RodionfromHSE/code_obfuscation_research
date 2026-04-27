"""Alternate entry point for SWE-bench experiments.

Exists so `python swebench_task/scripts/run.py <overrides>` works in IDE
debug configs. Delegates to `swebench_task.__main__.main` — keep all logic
there (`python -m swebench_task` is the canonical invocation).
"""
from boilerplate_tools import setup_root

setup_root(n_up=2, verbose=False)

from swebench_task.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
