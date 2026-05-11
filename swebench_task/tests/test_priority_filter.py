"""Test that `load_instances` respects `priority_ids` (prebuild workflow)."""
from pathlib import Path
from unittest.mock import patch

import yaml

from swebench_task.prebuild.image_selection import Bucket, PrebuildPlan
from swebench_task.prebuild.priority_yaml import (
    load_priority_ids,
    write_priority_yaml,
)
from swebench_task.source import dataset as dataset_mod


def _fake_rows(ids: list[str]) -> list[dict]:
    return [
        {
            "instance_id": iid,
            "repo": f"org/repo-{iid[:3]}",
            "base_commit": "deadbeef",
            "problem_statement": "x",
            "patch": "",
            "test_patch": "",
            "FAIL_TO_PASS": "[]",
            "PASS_TO_PASS": "[]",
            "hints_text": "",
            "version": "1",
        }
        for iid in ids
    ]


def _patched_load(ids: list[str]):
    rows = _fake_rows(ids)
    return patch.object(dataset_mod, "load_dataset", return_value=rows)


def test_priority_ids_filter_and_reorder():
    all_ids = ["c-3", "a-1", "b-2", "d-4"]
    with _patched_load(all_ids):
        insts = dataset_mod.load_instances(
            skip_ids=set(), priority_ids=["b-2", "a-1"],
        )
    assert [i.instance_id for i in insts] == ["b-2", "a-1"]


def test_priority_ids_honor_skip_list():
    all_ids = ["a-1", "b-2", "c-3"]
    with _patched_load(all_ids):
        insts = dataset_mod.load_instances(
            skip_ids={"b-2"}, priority_ids=["a-1", "b-2", "c-3"],
        )
    assert [i.instance_id for i in insts] == ["a-1", "c-3"]


def test_priority_ids_drops_unknown_ids():
    all_ids = ["a-1"]
    with _patched_load(all_ids):
        insts = dataset_mod.load_instances(
            skip_ids=set(), priority_ids=["a-1", "missing"],
        )
    assert [i.instance_id for i in insts] == ["a-1"]


def test_no_priority_ids_falls_back_to_shuffle():
    all_ids = ["a-1", "b-2", "c-3"]
    with _patched_load(all_ids), \
         patch.object(dataset_mod, "load_instance_order", return_value=None):
        insts_a = dataset_mod.load_instances(
            skip_ids=set(), priority_ids=None, shuffle_seed=1,
        )
        insts_b = dataset_mod.load_instances(
            skip_ids=set(), priority_ids=None, shuffle_seed=1,
        )
    assert [i.instance_id for i in insts_a] == [i.instance_id for i in insts_b]
    assert {i.instance_id for i in insts_a} == set(all_ids)


def test_priority_yaml_round_trip(tmp_path: Path):
    plan = PrebuildPlan(
        buckets=(Bucket(repo="r/x", version="1", instance_ids=("a", "b")),),
        instance_ids=("a", "b"),
        estimated_gb=7.4,
        budget_gb=40.0,
        top_k=3,
    )
    path = tmp_path / "priority.yaml"
    write_priority_yaml(plan, path)
    ids = load_priority_ids(path)
    assert ids == ["a", "b"]
    data = yaml.safe_load(path.read_text())
    assert data["buckets"][0]["repo"] == "r/x"


def test_load_priority_ids_returns_empty_if_missing(tmp_path: Path):
    assert load_priority_ids(tmp_path / "does_not_exist.yaml") == []
