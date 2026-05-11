"""Tests for SWE-bench run cache identity checks."""
from swebench_task.agent.runner import AgentRunResult
from swebench_task.obfuscation.identity import RepoIdentity
from swebench_task.obfuscation.protocol import RepoObfuscationResult
from swebench_task.obfuscation.rope_renamer import RopeRepoRenamer
from swebench_task.source.cache import CacheKey, RunCache, build_cache_key
from swebench_task.source.dataset import SWEBenchInstance
from swebench_task.utils.reporting import InstanceReport


def _instance(problem_statement: str = "fix the bug") -> SWEBenchInstance:
    return SWEBenchInstance(
        instance_id="org__repo-1",
        repo="org/repo",
        base_commit="abc123",
        problem_statement=problem_statement,
        patch="",
        test_patch="",
        fail_to_pass="[]",
        pass_to_pass="[]",
        hints_text="",
        version="",
    )


def _report(obfuscation_name: str = "rope_rename") -> InstanceReport:
    return InstanceReport(
        instance_id="org__repo-1",
        obfuscation_name=obfuscation_name,
        obfuscation=RepoObfuscationResult(symbols_renamed=1, files_modified=1),
        agent=AgentRunResult(instance_id="org__repo-1", model_patch="diff --git a/x b/x\n"),
    )


def test_cache_rejects_same_path_with_different_fingerprint(tmp_path):
    cache = RunCache(tmp_path)
    key = CacheKey("rope_rename", "openai/model", "org__repo-1", fingerprint="a")
    stale_key = CacheKey("rope_rename", "openai/model", "org__repo-1", fingerprint="b")

    assert key.as_path(tmp_path) == stale_key.as_path(tmp_path)

    cache.put(key, _report())

    assert cache.get(key) is not None
    assert cache.get(stale_key) is None


def test_cache_key_changes_when_obfuscation_config_changes(tmp_path):
    base = build_cache_key(
        instance=_instance(),
        obfuscation=RopeRepoRenamer(max_symbols=200),
        dataset_name="SWE-bench/SWE-bench_Verified",
        split="test",
        model_name="openai/model",
        max_turns=50,
        cost_limit=3.0,
        timeout_seconds=1200.0,
        api_base=None,
        cost_tracking="default",
    )
    changed = build_cache_key(
        instance=_instance(),
        obfuscation=RopeRepoRenamer(max_symbols=10),
        dataset_name="SWE-bench/SWE-bench_Verified",
        split="test",
        model_name="openai/model",
        max_turns=50,
        cost_limit=3.0,
        timeout_seconds=1200.0,
        api_base=None,
        cost_tracking="default",
    )

    assert base.as_path(tmp_path) == changed.as_path(tmp_path)
    assert base.fingerprint != changed.fingerprint


def test_cache_key_changes_when_agent_or_instance_changes():
    base = build_cache_key(
        instance=_instance(),
        obfuscation=RepoIdentity(),
        dataset_name="SWE-bench/SWE-bench_Verified",
        split="test",
        model_name="openai/model",
        max_turns=50,
        cost_limit=3.0,
        timeout_seconds=1200.0,
        api_base=None,
        cost_tracking="default",
    )
    different_agent = build_cache_key(
        instance=_instance(),
        obfuscation=RepoIdentity(),
        dataset_name="SWE-bench/SWE-bench_Verified",
        split="test",
        model_name="openai/model",
        max_turns=10,
        cost_limit=3.0,
        timeout_seconds=1200.0,
        api_base=None,
        cost_tracking="default",
    )
    different_problem = build_cache_key(
        instance=_instance(problem_statement="fix another bug"),
        obfuscation=RepoIdentity(),
        dataset_name="SWE-bench/SWE-bench_Verified",
        split="test",
        model_name="openai/model",
        max_turns=50,
        cost_limit=3.0,
        timeout_seconds=1200.0,
        api_base=None,
        cost_tracking="default",
    )

    assert base.fingerprint != different_agent.fingerprint
    assert base.fingerprint != different_problem.fingerprint
