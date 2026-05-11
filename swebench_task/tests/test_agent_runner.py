"""Tests for the SWE-bench mini-swe-agent runner wrapper."""
import json
from pathlib import Path

from swebench_task.agent import runner


class _FakeAgent:
    def __init__(self, *args, output_path: Path | None = None, **kwargs):
        self.output_path = output_path
        self.cost = 0.25
        self.n_calls = 1
        self.messages = [
            {
                "role": "assistant",
                "content": "I need to inspect the repo.",
                "extra": {
                    "actions": [{"cmd": "ls"}],
                    "response": {"choices": [{"message": {"content": "raw reply"}}]},
                },
            },
        ]

    def run(self, task: str) -> None:
        if self.output_path:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text(json.dumps({"messages": self.messages}))


def test_run_agent_saves_transcript(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "DefaultAgent", _FakeAgent)
    monkeypatch.setattr(runner, "TranscriptLitellmModel", lambda **kwargs: object())
    monkeypatch.setattr(runner, "LocalEnvironment", lambda **kwargs: object())
    monkeypatch.setattr(
        runner,
        "_load_default_templates",
        lambda: {"system_template": "system", "instance_template": "task: {{ task }}"},
    )
    monkeypatch.setattr(runner, "_git_diff", lambda repo_dir: "diff --git a/x b/x")

    transcripts_dir = tmp_path / "agent_transcripts"
    raw_responses_dir = tmp_path / "raw_model_responses"
    result = runner.run_agent(
        repo_dir=tmp_path,
        problem_statement="fix it",
        instance_id="pytest-dev/pytest-8399",
        model_name="openai/test-model",
        transcripts_dir=transcripts_dir,
        raw_responses_dir=raw_responses_dir,
    )

    transcript_path = transcripts_dir / "pytest-dev__pytest-8399.json"
    raw_responses_path = raw_responses_dir / "pytest-dev__pytest-8399.jsonl"
    assert result.transcript_path == str(transcript_path)
    assert result.raw_responses_path == str(raw_responses_path)
    assert transcript_path.exists()

    data = json.loads(transcript_path.read_text())
    assert data["messages"][0]["extra"]["response"]["choices"][0]["message"]["content"] == "raw reply"


def test_transcript_model_saves_raw_response_before_parsing(monkeypatch, tmp_path):
    class FakeResponse:
        def model_dump(self):
            return {"choices": [{"message": {"content": "plain text reply"}}]}

    monkeypatch.setattr(runner.LitellmModel, "_parse_actions", lambda self, response: [])

    path = tmp_path / "raw.jsonl"
    model = runner.TranscriptLitellmModel(
        model_name="openai/test-model",
        raw_responses_path=path,
    )

    assert model._parse_actions(FakeResponse()) == []

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["response"]["choices"][0]["message"]["content"] == "plain text reply"


def test_transcript_model_parses_mswea_bash_block(monkeypatch, tmp_path):
    class FakeMessage:
        tool_calls = None
        content = (
            "THOUGHT: I need to inspect the repo.\n\n"
            "```mswea_bash_command\n"
            "ls -la\n"
            "```"
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

        def model_dump(self):
            return {"choices": [{"message": {"content": FakeMessage.content}}]}

    def raise_format_error(self, response):
        raise runner.FormatError(
            {
                "role": "user",
                "content": "No tool calls found",
                "extra": {"interrupt_type": "FormatError"},
            }
        )

    monkeypatch.setattr(runner.LitellmModel, "_parse_actions", raise_format_error)

    model = runner.TranscriptLitellmModel(
        model_name="openai/test-model",
        raw_responses_path=tmp_path / "raw.jsonl",
    )

    assert model._parse_actions(FakeResponse()) == [{"command": "ls -la"}]


def test_guarded_environment_blocks_sudo():
    env = runner.GuardedLocalEnvironment(cwd=".")

    output = env.execute({"command": "sudo sed -i 's/a/b/' file.py"})

    assert output["returncode"] == 2
    assert "sudo is not available" in output["output"]


def test_guarded_environment_blocks_system_paths():
    env = runner.GuardedLocalEnvironment(cwd=".")

    output = env.execute({"command": "python /usr/lib/python3.6/site-packages/_pytest/unittest.py"})

    assert output["returncode"] == 2
    assert "current repository checkout" in output["output"]
