"""Tests for the MultiPL-E dataset adapter (entry-point extraction + row mapping)."""
import json

from code_obfuscation_research.datasets.multipl_e import (
    MultiPLEDatasetAdapter,
    _extract_js_entry_point,
)


def test_extract_entry_point_simple():
    prompt = "// add two numbers\nfunction add(a, b) {\n"
    assert _extract_js_entry_point(prompt) == "add"


def test_extract_entry_point_takes_last_match():
    prompt = (
        "function helper(x) { return x; }\n"
        "// main\n"
        "function main_fn(a, b) {\n"
    )
    assert _extract_js_entry_point(prompt) == "main_fn"


def test_extract_entry_point_dollar_sign_identifier():
    prompt = "function $unusual_name(a) {\n"
    assert _extract_js_entry_point(prompt) == "$unusual_name"


def test_extract_entry_point_none_when_no_function():
    assert _extract_js_entry_point("// just comments\n") is None


def test_row_to_sample_happy_path():
    adapter = MultiPLEDatasetAdapter()
    sample = adapter._row_to_sample({
        "name": "HumanEval_0_has_close_elements",
        "prompt": "function has_close_elements(numbers, threshold) {\n",
        "tests": "}\nconsole.log('ok');\n",
        "language": "js",
    })
    assert sample is not None
    assert sample.sample_id == "HumanEval_0_has_close_elements"
    assert sample.entry_point == "has_close_elements"
    assert sample.code.language == "javascript"
    assert sample.test.startswith("}")


def test_row_to_sample_skips_missing_fields():
    adapter = MultiPLEDatasetAdapter()
    assert adapter._row_to_sample({"name": "x"}) is None
    assert adapter._row_to_sample({"name": "x", "prompt": "", "tests": "x"}) is None
    assert adapter._row_to_sample({"name": "x", "prompt": "no function here", "tests": "x"}) is None


def test_load_from_local(tmp_path):
    rows = [
        {
            "name": "HumanEval_1_foo",
            "prompt": "function foo(a) {\n",
            "tests": "}\nconsole.log('ok');\n",
        },
        {
            "name": "HumanEval_2_bar",
            "prompt": "function bar(b) {\n",
            "tests": "}\nconsole.log('ok');\n",
        },
    ]
    path = tmp_path / "rows.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    adapter = MultiPLEDatasetAdapter(local_path=str(path))
    samples = adapter.load_split()
    assert len(samples) == 2
    assert samples[0].entry_point == "foo"
    assert samples[1].entry_point == "bar"

    limited = adapter.load_split(limit=1)
    assert len(limited) == 1
    assert limited[0].sample_id == "HumanEval_1_foo"
