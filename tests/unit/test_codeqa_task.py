"""Tests for CodeQA task definition."""
from code_obfuscation_research.domain import CodeArtifact, CodeQASample, ModelResponse
from code_obfuscation_research.tasks.codeqa import CodeQATask


def _make_sample() -> CodeQASample:
    return CodeQASample(
        sample_id="s1",
        code=CodeArtifact(artifact_id="a1", text="def add(a, b): return a + b"),
        question="What does the function return?",
        answer="The sum of a and b.",
    )


def test_build_request():
    task = CodeQATask()
    sample = _make_sample()
    req = task.build_request(sample, sample.code)
    assert req.sample_id == "s1"
    assert len(req.messages) == 2
    assert req.messages[0]["role"] == "system"
    assert "def add(a, b)" in req.messages[1]["content"]
    assert sample.question in req.messages[1]["content"]


def test_parse_prediction():
    task = CodeQATask()
    sample = _make_sample()
    resp = ModelResponse(sample_id="s1", perturbation_name="noop", text="  The sum.  ")
    assert task.parse_prediction(sample, resp) == "The sum."


def test_build_reference():
    task = CodeQATask()
    sample = _make_sample()
    assert task.build_reference(sample) == "The sum of a and b."


def test_build_eval_case():
    task = CodeQATask()
    sample = _make_sample()
    ec = task.build_eval_case(sample, "The sum.", "The sum of a and b.", "noop")
    assert ec.sample_id == "s1"
    assert ec.actual_output == "The sum."
    assert ec.expected_output == "The sum of a and b."
    assert ec.perturbation_name == "noop"
    assert ec.input_text == sample.question
