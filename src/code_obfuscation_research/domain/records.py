"""Run and evaluation record types persisted as JSONL."""
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """Internal representation of a prompt sent to the model."""

    sample_id: str
    perturbation_name: str
    messages: list[dict[str, str]]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """Internal representation of a model reply."""

    sample_id: str
    perturbation_name: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One inference result persisted in JSONL."""

    sample_id: str
    perturbation_name: str
    request_messages: list[dict[str, str]]
    response_text: str
    reference_text: str
    perturbation_stats: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunRecord":
        return cls(**d)


@dataclass(frozen=True, slots=True)
class EvalCase:
    """A single evaluation case for metrics."""

    sample_id: str
    input_text: str
    actual_output: str
    expected_output: str
    perturbation_name: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
