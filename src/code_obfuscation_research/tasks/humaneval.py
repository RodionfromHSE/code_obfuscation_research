"""HumanEval task definition for function synthesis."""
import re

from code_obfuscation_research.domain import (
    CodeArtifact,
    EvalCase,
    HumanEvalSample,
    ModelRequest,
    ModelResponse,
)

SYSTEM_PROMPT_TEMPLATE = (
    "You are a {language} coding assistant. "
    "Complete the function implementation. "
    "Return only {language} code, no markdown and no explanation."
)

_CODE_BLOCK_RE = re.compile(r"```(?:[A-Za-z0-9_+#.-]+)?\s*\n(?P<code>[\s\S]*?)```", re.IGNORECASE)


def _extract_code(text: str) -> str:
    match = _CODE_BLOCK_RE.search(text)
    if not match:
        return text
    return match.group("code")


class HumanEvalTask:
    """Turns HumanEvalSample into model requests and execution-ready eval cases."""

    def __init__(self, name: str = "humaneval"):
        self.name = name

    def build_request(self, sample: HumanEvalSample, code: CodeArtifact) -> ModelRequest:
        language = code.language or sample.code.language
        return ModelRequest(
            sample_id=sample.sample_id,
            perturbation_name="",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(language=language)},
                {"role": "user", "content": code.text},
            ],
            metadata={
                "task_type": "humaneval",
                "entry_point": sample.entry_point,
                "test": sample.test,
                "prompt": code.text,
                "language": language,
            },
        )

    def parse_prediction(self, sample: HumanEvalSample, response: ModelResponse) -> str:
        del sample
        return _extract_code(response.text).rstrip()

    def build_reference(self, sample: HumanEvalSample) -> str:
        return sample.canonical_solution

    def build_eval_case(
        self,
        sample: HumanEvalSample,
        prediction: str,
        reference: str,
        perturbation_name: str,
    ) -> EvalCase:
        return EvalCase(
            sample_id=sample.sample_id,
            input_text=sample.code.text,
            actual_output=prediction,
            expected_output=reference,
            perturbation_name=perturbation_name,
            metadata={
                "task_type": "humaneval",
                "entry_point": sample.entry_point,
                "test": sample.test,
                "prompt": sample.code.text,
                "language": sample.code.language,
            },
        )
