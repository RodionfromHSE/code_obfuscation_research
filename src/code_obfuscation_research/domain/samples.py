"""Task sample types: base and task-specific."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .code import CodeArtifact


@dataclass(frozen=True, slots=True)
class CodeTaskSample:
    """Base sample: anything that carries at least one code artifact."""

    sample_id: str
    code: CodeArtifact
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CodeQASample(CodeTaskSample):
    """Sample for code question-answering tasks."""

    question: str = ""
    answer: str = ""


@dataclass(frozen=True, slots=True)
class HumanEvalSample(CodeTaskSample):
    """Sample for HumanEval program synthesis (prompt + official tests)."""

    entry_point: str = ""
    test: str = ""
    canonical_solution: str = ""
