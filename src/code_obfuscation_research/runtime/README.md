# runtime/

Shared infrastructure used by both the run and eval pipelines: LLM invocation, caching, and artifact storage.

## LLMRuntime (`llm_runtime.py`)

Wraps a LangChain `BaseChatModel` and provides:

- `invoke(request)` -- sync call, returns `ModelResponse`
- `ainvoke(request)` -- async call, bounded by `asyncio.Semaphore(max_concurrent)` to avoid firing all requests at once
- `invoke_structured(request, output_schema)` -- Pydantic-based parsing with retry (see below)

All calls go through `tracked_cache_scope()` so cache invalidation works.

## Cache invalidation (`cache.py`)

Problem: if the model returns a malformed response and it gets cached, retrying will keep returning the same bad response.

Solution: `InvalidatableSQLiteCache` extends LangChain's `SQLiteCache` with scope-based invalidation.

1. Every LLM call runs inside `tracked_cache_scope()`
2. The scope records all `(prompt, llm_string)` keys looked up during the call
3. If the caller decides the response is bad, `scope.invalidate()` deletes those specific rows from SQLite
4. The next retry hits the API fresh instead of returning the cached garbage

This is used by `invoke_structured()`: on Pydantic parse failure, it invalidates the cache entries and retries up to `max_parse_retries` times.

## RunStore (`store.py`)

Append-only JSONL writer. Clears the output file on init to prevent duplicate records when re-running the same experiment.
