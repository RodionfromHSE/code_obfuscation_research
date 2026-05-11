"""LangChain factory for OpenAI-compatible local vLLM servers."""
import logging
from typing import Any

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


def create_vllm_model(
    model_name: str,
    base_url: str,
    temperature: float = 0.0,
    seed: int | None = None,
    max_retries: int = 3,
    timeout: int = 120,
    max_tokens: int | None = None,
    top_p: float | None = None,
    api_key: str = "EMPTY",
    **kwargs: Any,
) -> ChatOpenAI:
    """Create a ChatOpenAI client pointed at a local OpenAI-compatible vLLM endpoint."""
    model = ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        seed=seed,
        top_p=top_p,
        max_retries=max_retries,
        timeout=timeout,
        max_tokens=max_tokens,
        model_kwargs=kwargs,
    )
    logger.info("Created vLLM OpenAI-compatible model=%s base_url=%s", model_name, base_url)
    return model
