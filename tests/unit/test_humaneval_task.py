"""Tests for HumanEval task definition."""
from code_obfuscation_research.domain import CodeArtifact, HumanEvalSample, ModelResponse
from code_obfuscation_research.tasks.humaneval import HumanEvalTask


def _make_sample() -> HumanEvalSample:
    return HumanEvalSample(
        sample_id="HumanEval/14",
        code=CodeArtifact(
            artifact_id="HumanEval_14_prompt",
            text=(
                "from typing import List\n\n"
                "def all_prefixes(string: str) -> List[str]:\n"
                '    """Return list of all prefixes from shortest to longest."""\n'
            ),
        ),
        entry_point="all_prefixes",
        test=(
            "def check(candidate):\n"
            "    assert candidate('') == []\n"
            "    assert candidate('abc') == ['a', 'ab', 'abc']\n"
        ),
        canonical_solution="    return [string[:i + 1] for i in range(len(string))]",
    )


def test_build_request():
    task = HumanEvalTask()
    sample = _make_sample()
    req = task.build_request(sample, sample.code)
    assert req.sample_id == sample.sample_id
    assert len(req.messages) == 2
    assert req.messages[0]["role"] == "system"
    assert req.messages[1]["content"] == sample.code.text
    assert req.metadata["entry_point"] == sample.entry_point
    assert req.metadata["test"] == sample.test
    assert req.metadata["prompt"] == sample.code.text


def test_parse_prediction_extracts_code_fence():
    task = HumanEvalTask()
    sample = _make_sample()
    resp = ModelResponse(
        sample_id=sample.sample_id,
        perturbation_name="noop",
        text="```python\n    return [string[:i+1] for i in range(len(string))]\n```",
    )
    assert task.parse_prediction(sample, resp) == "    return [string[:i+1] for i in range(len(string))]"


def test_build_eval_case():
    task = HumanEvalTask()
    sample = _make_sample()
    prediction = "    return []"
    reference = task.build_reference(sample)
    case = task.build_eval_case(sample, prediction, reference, "noop")
    assert case.sample_id == sample.sample_id
    assert case.actual_output == prediction
    assert case.expected_output == reference
    assert case.metadata["entry_point"] == "all_prefixes"
    assert case.metadata["test"] == sample.test
