"""Code question-answering task definition."""
from code_obfuscation_research.domain import (
    CodeArtifact,
    CodeQASample,
    EvalCase,
    ModelRequest,
    ModelResponse,
)

SYSTEM_PROMPT = (
    "You are a code comprehension assistant. "
    "Given a code snippet and a question about it, provide a concise and accurate answer."
)


class CodeQATask:
    """Turns CodeQASample into model requests and evaluation cases."""

    def __init__(self, name: str = "codeqa"):
        self.name = name

    def build_request(self, sample: CodeQASample, code: CodeArtifact) -> ModelRequest:
        user_content = f"Code:\n```{code.language}\n{code.text}\n```\n\nQuestion: {sample.question}"
        return ModelRequest(
            sample_id=sample.sample_id,
            perturbation_name="",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )

    def parse_prediction(self, sample: CodeQASample, response: ModelResponse) -> str:
        return response.text.strip()

    def build_reference(self, sample: CodeQASample) -> str:
        return sample.answer

    def build_eval_case(
        self,
        sample: CodeQASample,
        prediction: str,
        reference: str,
        perturbation_name: str,
    ) -> EvalCase:
        return EvalCase(
            sample_id=sample.sample_id,
            input_text=sample.question,
            actual_output=prediction,
            expected_output=reference,
            perturbation_name=perturbation_name,
        )
