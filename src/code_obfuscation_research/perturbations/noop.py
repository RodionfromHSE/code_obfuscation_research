"""No-op perturbation: returns code unchanged."""
from code_obfuscation_research.domain import PerturbationInput, PerturbationResult


class NoOpPerturbation:
    """Baseline perturbation that does nothing."""

    def __init__(self, name: str = "noop"):
        self.name = name

    def apply(self, item: PerturbationInput) -> PerturbationResult:
        return PerturbationResult(perturbed_code=item.code, applied=False)
