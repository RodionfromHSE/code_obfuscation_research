"""Tests for RunStore JSONL persistence."""
from code_obfuscation_research.domain import RunRecord
from code_obfuscation_research.runtime.store import RunStore


def test_append_and_load(tmp_path):
    store = RunStore(output_dir=tmp_path, experiment_name="test", perturbation_name="noop")
    r1 = RunRecord(
        sample_id="s1",
        perturbation_name="noop",
        request_messages=[{"role": "user", "content": "hi"}],
        response_text="hello",
        reference_text="hello",
    )
    r2 = RunRecord(
        sample_id="s2",
        perturbation_name="noop",
        request_messages=[{"role": "user", "content": "bye"}],
        response_text="goodbye",
        reference_text="goodbye",
    )
    store.append(r1)
    store.append(r2)

    loaded = store.load_all()
    assert len(loaded) == 2
    assert loaded[0] == r1
    assert loaded[1] == r2


def test_load_empty(tmp_path):
    store = RunStore(output_dir=tmp_path, experiment_name="empty", perturbation_name="noop")
    assert store.load_all() == []


def test_load_from_path(tmp_path):
    store = RunStore(output_dir=tmp_path, experiment_name="test", perturbation_name="x")
    r = RunRecord(
        sample_id="s1",
        perturbation_name="x",
        request_messages=[],
        response_text="out",
        reference_text="ref",
    )
    store.append(r)
    loaded = RunStore.load_from_path(store.path)
    assert loaded == [r]


def test_clears_on_reinit(tmp_path):
    store1 = RunStore(output_dir=tmp_path, experiment_name="dup", perturbation_name="noop")
    store1.append(RunRecord(
        sample_id="s1", perturbation_name="noop",
        request_messages=[], response_text="a", reference_text="a",
    ))
    assert len(store1.load_all()) == 1

    store2 = RunStore(output_dir=tmp_path, experiment_name="dup", perturbation_name="noop")
    store2.append(RunRecord(
        sample_id="s2", perturbation_name="noop",
        request_messages=[], response_text="b", reference_text="b",
    ))
    loaded = store2.load_all()
    assert len(loaded) == 1
    assert loaded[0].sample_id == "s2"
