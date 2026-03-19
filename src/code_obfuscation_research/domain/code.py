"""Core code artifact and perturbation domain types."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CodeArtifact:
    """A piece of source code that perturbations can transform."""

    artifact_id: str
    text: str
    language: str = "python"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def with_text(self, new_text: str) -> "CodeArtifact":
        return CodeArtifact(
            artifact_id=self.artifact_id,
            text=new_text,
            language=self.language,
            metadata=self.metadata,
        )


@dataclass(frozen=True, slots=True)
class PerturbationInput:
    """Input to a perturbation transform."""

    code: CodeArtifact
    sample_id: str | None = None
    task_name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PerturbationResult:
    """Output of a perturbation transform."""

    perturbed_code: CodeArtifact
    applied: bool
    stats: Mapping[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
