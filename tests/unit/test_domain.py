"""Tests for domain entities and protocols."""
from code_obfuscation_research.domain import (
    CodeArtifact,
    CodeQASample,
    CodeTaskSample,
    EvalCase,
    ModelRequest,
    ModelResponse,
    PerturbationInput,
    PerturbationResult,
    RunRecord,
)


def _make_artifact(text: str = "def foo(): pass") -> CodeArtifact:
    return CodeArtifact(artifact_id="a1", text=text)


def _make_qa_sample() -> CodeQASample:
    return CodeQASample(
        sample_id="s1",
        code=_make_artifact(),
        question="What does foo do?",
        answer="It does nothing.",
    )


class TestCodeArtifact:
    def test_frozen(self):
        a = _make_artifact()
        try:
            a.text = "changed"  # type: ignore[misc]
            assert False, "should be frozen"
        except AttributeError:
            pass

    def test_with_text(self):
        a = _make_artifact("original")
        b = a.with_text("new")
        assert b.text == "new"
        assert b.artifact_id == a.artifact_id
        assert a.text == "original"


class TestCodeQASample:
    def test_inherits_code_task_sample(self):
        s = _make_qa_sample()
        assert isinstance(s, CodeTaskSample)
        assert s.code.text == "def foo(): pass"
        assert s.question == "What does foo do?"


class TestRunRecord:
    def test_round_trip(self):
        r = RunRecord(
            sample_id="s1",
            perturbation_name="noop",
            request_messages=[{"role": "user", "content": "hi"}],
            response_text="hello",
            reference_text="hello",
        )
        d = r.to_dict()
        r2 = RunRecord.from_dict(d)
        assert r == r2

    def test_dict_keys(self):
        r = RunRecord(
            sample_id="s1",
            perturbation_name="noop",
            request_messages=[],
            response_text="",
            reference_text="",
        )
        d = r.to_dict()
        assert "sample_id" in d
        assert "perturbation_name" in d


class TestPerturbationTypes:
    def test_input_defaults(self):
        p = PerturbationInput(code=_make_artifact())
        assert p.sample_id is None
        assert p.task_name is None

    def test_result_success(self):
        r = PerturbationResult(
            perturbed_code=_make_artifact("def bar(): pass"),
            applied=True,
            stats={"renamed_functions": 1},
        )
        assert r.applied
        assert r.stats["renamed_functions"] == 1
        assert r.error is None


class TestModelTypes:
    def test_model_request(self):
        req = ModelRequest(
            sample_id="s1",
            perturbation_name="noop",
            messages=[{"role": "user", "content": "hello"}],
        )
        assert req.messages[0]["role"] == "user"

    def test_model_response(self):
        resp = ModelResponse(sample_id="s1", perturbation_name="noop", text="answer")
        assert resp.text == "answer"

    def test_eval_case(self):
        ec = EvalCase(
            sample_id="s1",
            input_text="question",
            actual_output="pred",
            expected_output="ref",
            perturbation_name="noop",
        )
        assert ec.actual_output == "pred"
