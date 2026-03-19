"""LangChain OpenAI model factory."""
import logging
from typing import Any

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


def create_openai_model(
    model_name: str,
    temperature: float = 0.0,
    seed: int | None = None,
    max_retries: int = 3,
    timeout: int = 60,
    max_tokens: int | None = None,
    top_p: float | None = None,
    reasoning_effort: str | None = None,
    **kwargs: Any,
) -> ChatOpenAI:
    """Create a ChatOpenAI instance with full parameter support.

    GPT-5.4 models only support temperature/seed when reasoning_effort='none'.
    If reasoning_effort is set to something else, temperature and seed are dropped.
    """
    model_kwargs: dict[str, Any] = {}

    has_reasoning = reasoning_effort is not None and reasoning_effort != "none"

    if reasoning_effort is not None:
        model_kwargs["reasoning_effort"] = reasoning_effort

    effective_temp = temperature if not has_reasoning else None
    effective_seed = seed if not has_reasoning else None

    model_kwargs.update(kwargs)

    model = ChatOpenAI(
        model=model_name,
        temperature=effective_temp,
        seed=effective_seed,
        top_p=top_p,
        max_retries=max_retries,
        timeout=timeout,
        max_tokens=max_tokens,
        model_kwargs=model_kwargs,
    )
    logger.info(
        "Created ChatOpenAI model=%s temperature=%s reasoning_effort=%s",
        model_name, effective_temp, reasoning_effort,
    )
    return model
