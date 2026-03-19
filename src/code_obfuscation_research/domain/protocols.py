"""Protocol interfaces for pluggable components."""
from typing import Protocol, TypeVar, runtime_checkable

from .code import CodeArtifact, PerturbationInput, PerturbationResult
from .records import EvalCase, ModelRequest, ModelResponse
from .samples import CodeTaskSample

SampleT = TypeVar("SampleT", bound=CodeTaskSample)


@runtime_checkable
class DatasetAdapter(Protocol[SampleT]):
    def load_split(self, split: str, limit: int | None = None) -> list[SampleT]: ...


@runtime_checkable
class TaskDefinition(Protocol[SampleT]):
    name: str

    def build_request(self, sample: SampleT, code: CodeArtifact) -> ModelRequest: ...

    def parse_prediction(self, sample: SampleT, response: ModelResponse) -> str: ...

    def build_reference(self, sample: SampleT) -> str: ...

    def build_eval_case(
        self,
        sample: SampleT,
        prediction: str,
        reference: str,
        perturbation_name: str,
    ) -> EvalCase: ...


@runtime_checkable
class Perturbation(Protocol):
    name: str

    def apply(self, item: PerturbationInput) -> PerturbationResult: ...
