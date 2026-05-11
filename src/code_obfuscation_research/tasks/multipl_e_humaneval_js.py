"""MultiPL-E HumanEval-JS task: JavaScript function synthesis."""
import re

from code_obfuscation_research.domain import (
    CodeArtifact,
    EvalCase,
    HumanEvalSample,
    ModelRequest,
    ModelResponse,
)

SYSTEM_PROMPT = (
    "You are a JavaScript coding assistant. "
    "Complete the function implementation. "
    "Return only JavaScript code, no markdown and no explanation."
)

_CODE_BLOCK_RE = re.compile(r"```(?:javascript|js)?\s*\n(?P<code>[\s\S]*?)```", re.IGNORECASE)

TASK_TYPE = "multipl_e_humaneval_js"
LANGUAGE = "javascript"


def _extract_code(text: str) -> str:
    match = _CODE_BLOCK_RE.search(text)
    if not match:
        return text
    return match.group("code")


class MultiPLEHumanEvalJSTask:
    """Turns HumanEvalSample (JS) into model requests and execution-ready eval cases."""

    def __init__(self, name: str = "multipl_e_humaneval_js"):
        self.name = name

    def _metadata(self, sample: HumanEvalSample, prompt_text: str) -> dict:
        return {
            "task_type": TASK_TYPE,
            "language": LANGUAGE,
            "entry_point": sample.entry_point,
            "test": sample.test,
            "prompt": prompt_text,
        }

    def build_request(self, sample: HumanEvalSample, code: CodeArtifact) -> ModelRequest:
        return ModelRequest(
            sample_id=sample.sample_id,
            perturbation_name="",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": code.text},
            ],
            metadata=self._metadata(sample, code.text),
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
            metadata=self._metadata(sample, sample.code.text),
        )
