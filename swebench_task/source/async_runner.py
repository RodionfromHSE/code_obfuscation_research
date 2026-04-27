"""Bounded async orchestration of sync per-instance work.

Wraps a sync `process_fn(instance) -> T` in asyncio with a semaphore cap.
Each call runs in the default ThreadPoolExecutor (`asyncio.to_thread`), so
existing sync code (`run_agent`, rope, git clone) is reused untouched.

rope per-symbol timeout uses signal.alarm, which only works on the main
thread. Under concurrency>1 rope runs on worker threads with timeout
disabled; this is acceptable because each instance's overall wall-clock
is bounded by `agent.timeout_seconds`.
"""
import asyncio
import logging
from collections.abc import Callable

from tqdm.asyncio import tqdm as tqdm_async

logger = logging.getLogger(__name__)


async def run_bounded_ordered[T, U](
    items: list[T],
    process_fn: Callable[[T], U],
    concurrency: int,
    desc: str = "Agents",
    on_complete: Callable[[int, int, T, U], None] | None = None,
) -> list[U]:
    """Run process_fn over items with at most `concurrency` in flight.

    Output order matches input order (asyncio.gather). Each task runs the sync
    `process_fn` in the default ThreadPoolExecutor via asyncio.to_thread, so
    existing sync code (run_agent, rope, git clone) works unchanged.

    `on_complete(completed_so_far, total, item, result)` fires as each task
    finishes — indices reflect *completion* order under concurrency, not input
    order. The callback runs on the event-loop thread, so it's safe to share
    mutable state with it.
    """
    if not items:
        return []
    sem = asyncio.Semaphore(max(concurrency, 1))
    pbar = tqdm_async(total=len(items), desc=desc, unit="inst")
    total = len(items)
    completed = 0

    async def _run(item: T) -> U:
        nonlocal completed
        async with sem:
            res = await asyncio.to_thread(process_fn, item)
            completed += 1
            pbar.update(1)
            if on_complete is not None:
                on_complete(completed, total, item, res)
            return res

    try:
        return await asyncio.gather(*[_run(it) for it in items])
    finally:
        pbar.close()
