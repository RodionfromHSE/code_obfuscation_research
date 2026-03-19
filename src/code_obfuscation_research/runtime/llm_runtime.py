"""Shared LLM runtime: invoke with retry, parse-aware cache invalidation, async support."""
import asyncio
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from code_obfuscation_research.domain import ModelRequest, ModelResponse
from code_obfuscation_research.runtime.cache import tracked_cache_scope

logger = logging.getLogger(__name__)

_ROLE_MAP = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}


def _to_langchain_messages(messages: list[dict[str, str]]) -> list:
    return [_ROLE_MAP[m["role"]](content=m["content"]) for m in messages]


def _extract_text(result: Any) -> str:
    return result.content if isinstance(result.content, str) else str(result.content)


class LLMRuntime:
    """Wraps a LangChain chat model with parse-aware retry and cache invalidation."""

    def __init__(
        self,
        model: BaseChatModel,
        max_parse_retries: int = 2,
        max_concurrent: int = 16,
    ):
        self.model = model
        self.max_parse_retries = max_parse_retries
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def invoke(self, request: ModelRequest) -> ModelResponse:
        lc_messages = _to_langchain_messages(request.messages)
        with tracked_cache_scope():
            result = self.model.invoke(lc_messages)
        return ModelResponse(
            sample_id=request.sample_id,
            perturbation_name=request.perturbation_name,
            text=_extract_text(result),
        )

    def invoke_structured(
        self,
        request: ModelRequest,
        output_schema: type[BaseModel],
    ) -> tuple[ModelResponse, BaseModel | None]:
        """Invoke with Pydantic parsing; retries with cache invalidation on parse failure."""
        lc_messages = _to_langchain_messages(request.messages)
        last_error: Exception | None = None
        raw_text = ""

        for attempt in range(1 + self.max_parse_retries):
            with tracked_cache_scope() as scope:
                result = self.model.invoke(lc_messages)
            raw_text = _extract_text(result)
            try:
                parsed = output_schema.model_validate_json(raw_text)
                return (
                    ModelResponse(
                        sample_id=request.sample_id,
                        perturbation_name=request.perturbation_name,
                        text=raw_text,
                    ),
                    parsed,
                )
            except Exception as e:
                last_error = e
                logger.warning("Parse attempt %d/%d failed: %s", attempt + 1, self.max_parse_retries + 1, e)
                if attempt < self.max_parse_retries:
                    scope.invalidate()

        logger.error("All parse retries exhausted, returning raw text. Last error: %s", last_error)
        return (
            ModelResponse(
                sample_id=request.sample_id,
                perturbation_name=request.perturbation_name,
                text=raw_text,
            ),
            None,
        )

    async def ainvoke(self, request: ModelRequest) -> ModelResponse:
        lc_messages = _to_langchain_messages(request.messages)
        async with self._semaphore:
            with tracked_cache_scope():
                result = await self.model.ainvoke(lc_messages)
        return ModelResponse(
            sample_id=request.sample_id,
            perturbation_name=request.perturbation_name,
            text=_extract_text(result),
        )

    async def ainvoke_batch(self, requests: list[ModelRequest]) -> list[ModelResponse]:
        return await asyncio.gather(*(self.ainvoke(r) for r in requests))
