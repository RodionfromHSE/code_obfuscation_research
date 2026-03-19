"""Tests for cache invalidation scopes."""
from code_obfuscation_research.runtime.cache import (
    CacheScope,
    InvalidatableSQLiteCache,
    _NullScope,
    tracked_cache_scope,
)


def test_null_scope_invalidate_is_noop():
    scope = _NullScope()
    assert scope.invalidate() is False


def test_scope_records_keys(tmp_path):
    cache = InvalidatableSQLiteCache(database_path=str(tmp_path / "test.db"))
    scope = CacheScope(cache)
    scope.record("prompt1", "llm1")
    scope.record("prompt2", "llm2")
    scope.record("prompt1", "llm1")  # duplicate
    assert len(scope._keys) == 2


def test_tracked_scope_context_manager(tmp_path):
    cache = InvalidatableSQLiteCache(database_path=str(tmp_path / "test.db"))
    assert len(cache._active_scopes) == 0
    with cache.tracked_scope() as scope:
        assert len(cache._active_scopes) == 1
        cache.lookup("prompt", "llm")
        assert ("prompt", "llm") in scope._keys
    assert len(cache._active_scopes) == 0


def test_tracked_cache_scope_without_cache():
    """When no invalidatable cache is set, yields a null scope."""
    from langchain_core.globals import set_llm_cache
    set_llm_cache(None)
    with tracked_cache_scope() as scope:
        assert isinstance(scope, _NullScope)
