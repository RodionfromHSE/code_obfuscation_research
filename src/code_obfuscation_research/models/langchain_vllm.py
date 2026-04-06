"""LangChain model factory for vLLM-served models (OpenAI-compatible API)."""
import logging
from typing import Any

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


def create_vllm_model(
    model_name: str,
    base_url: str = "http://localhost:8000/v1",
    temperature: float = 0.0,
    seed: int | None = None,
    max_retries: int = 3,
    timeout: int = 120,
    max_tokens: int | None = 2048,
    top_p: float | None = None,
    **kwargs: Any,
) -> ChatOpenAI:
    """Create a ChatOpenAI instance pointed at a vLLM server."""
    model_kwargs: dict[str, Any] = {}
    model_kwargs.update(kwargs)

    model = ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key="not-needed",
        temperature=temperature,
        seed=seed,
        top_p=top_p,
        max_retries=max_retries,
        timeout=timeout,
        max_tokens=max_tokens,
        model_kwargs=model_kwargs,
    )
    logger.info(
        "Created vLLM model=%s base_url=%s temperature=%s",
        model_name, base_url, temperature,
    )
    return model
