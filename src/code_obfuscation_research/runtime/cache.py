"""Persistent SQLite cache with scope-based invalidation for parse-aware retries."""
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langchain_community.cache import SQLiteCache
from langchain_core.globals import get_llm_cache, set_llm_cache
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class CacheScope:
    """Collects cache keys looked up within a scope; can invalidate them all."""

    def __init__(self, cache: "InvalidatableSQLiteCache") -> None:
        self._cache = cache
        self._keys: set[tuple[str, str]] = set()

    def record(self, prompt: str, llm_string: str) -> None:
        self._keys.add((prompt, llm_string))

    def invalidate(self) -> bool:
        if not self._keys:
            return False
        with Session(self._cache.engine) as session:
            for prompt, llm_string in self._keys:
                session.query(self._cache.cache_schema).filter(
                    self._cache.cache_schema.prompt == prompt,
                    self._cache.cache_schema.llm == llm_string,
                ).delete()
            session.commit()
        count = len(self._keys)
        self._keys.clear()
        logger.debug("Invalidated %d cached entries", count)
        return True


class _NullScope:
    """No-op scope when cache is not invalidatable."""

    def invalidate(self) -> bool:
        return False


class InvalidatableSQLiteCache(SQLiteCache):
    """SQLiteCache with scope-based invalidation for retry flows."""

    def __init__(self, database_path: str) -> None:
        super().__init__(database_path=database_path)
        self._active_scopes: list[CacheScope] = []

    def lookup(self, prompt: str, llm_string: str):
        for scope in self._active_scopes:
            scope.record(prompt, llm_string)
        return super().lookup(prompt, llm_string)

    @contextmanager
    def tracked_scope(self) -> Iterator[CacheScope]:
        scope = CacheScope(self)
        self._active_scopes.append(scope)
        try:
            yield scope
        finally:
            self._active_scopes.remove(scope)


@contextmanager
def tracked_cache_scope() -> Iterator[CacheScope | _NullScope]:
    """Yields a scope recording all cache lookups; invalidate() clears them."""
    cache = get_llm_cache()
    if cache is not None and hasattr(cache, "tracked_scope"):
        with cache.tracked_scope() as scope:
            yield scope
    else:
        yield _NullScope()


def setup_cache(cache_db: str | Path) -> InvalidatableSQLiteCache:
    """Initialize a persistent invalidatable SQLite cache and register it globally."""
    path = Path(cache_db)
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = InvalidatableSQLiteCache(database_path=str(path))
    set_llm_cache(cache)
    logger.info("LLM cache initialized at %s", path)
    return cache
