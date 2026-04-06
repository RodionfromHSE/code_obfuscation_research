"""DeepEval-compatible judge model backed by a vLLM server (OpenAI-compatible API)."""
import logging
from typing import Any

from deepeval.models import DeepEvalBaseLLM
from openai import AsyncOpenAI, OpenAI

logger = logging.getLogger(__name__)


class VLLMJudge(DeepEvalBaseLLM):
    """Wraps a vLLM endpoint for use as a DeepEval judge model."""

    def __init__(
        self,
        model_name: str,
        base_url: str = "http://localhost:8000/v1",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ):
        self._model_name = model_name
        self._base_url = base_url
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client: OpenAI | None = None
        self._async_client: AsyncOpenAI | None = None
        super().__init__(model=model_name)

    def load_model(self) -> "VLLMJudge":
        self._client = OpenAI(base_url=self._base_url, api_key="not-needed")
        self._async_client = AsyncOpenAI(base_url=self._base_url, api_key="not-needed")
        logger.info("Loaded vLLM judge model=%s base_url=%s", self._model_name, self._base_url)
        return self

    def generate(self, prompt: str, **kwargs: Any) -> str:
        assert self._client is not None
        resp = self._client.chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def a_generate(self, prompt: str, **kwargs: Any) -> str:
        assert self._async_client is not None
        resp = await self._async_client.chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return resp.choices[0].message.content or ""

    def get_model_name(self) -> str:
        return self._model_name


def create_vllm_judge(
    model_name: str,
    base_url: str = "http://localhost:8000/v1",
    temperature: float = 0.0,
    max_tokens: int = 2048,
    **_kwargs: Any,
) -> VLLMJudge:
    """Factory for Hydra instantiation."""
    return VLLMJudge(
        model_name=model_name,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
    )
