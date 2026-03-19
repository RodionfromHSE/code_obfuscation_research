# domain/

Immutable entities and protocol interfaces. Everything here is frozen dataclasses or `Protocol` definitions -- no IO, no side effects.

## Entities

- `CodeArtifact` -- a piece of source code (text + language + id). This is what perturbations transform. Use `with_text()` to create a copy with new content.
- `CodeTaskSample` -- base sample: sample_id + one `CodeArtifact` + metadata. Every dataset adapter must produce at least this.
- `CodeQASample(CodeTaskSample)` -- adds `question` and `answer` fields for QA tasks.
- `PerturbationInput` / `PerturbationResult` -- input/output of a perturbation. Result carries `applied`, `stats` (e.g. renamed symbol count), and optional `error`.
- `ModelRequest` / `ModelResponse` -- internal prompt/response representation. Messages are plain dicts, not LangChain objects, so they don't leak outside `runtime/`.
- `RunRecord` -- one inference result persisted in JSONL. Includes request messages, response text, reference text, and perturbation stats.
- `EvalCase` -- input to the evaluator: question, actual output, expected output, perturbation name.

## Protocols (contracts)

Three pluggable protocols that the pipeline depends on:

- **`DatasetAdapter[SampleT]`** -- `load_split(split, limit) -> list[SampleT]`. Normalizes external data into domain samples immediately. Nothing outside the adapter should ever see raw HF dicts.
- **`TaskDefinition[SampleT]`** -- turns a sample + code into a model request, parses the response, builds the reference answer, and creates an eval case. This is where prompt templates and output parsing live.
- **`Perturbation`** -- `apply(PerturbationInput) -> PerturbationResult`. Transforms only the `CodeArtifact`. Never touches prompts, models, or dataset-specific fields.

The key design constraint: perturbations and runtime are task-agnostic. Only `DatasetAdapter` and `TaskDefinition` change when adding a new benchmark.
