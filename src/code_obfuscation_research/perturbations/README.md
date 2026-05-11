# perturbations/

Code-first transforms that rewrite `CodeArtifact` before the code is sent to the model. Perturbations never see prompts, model objects, or dataset-specific fields.

## noop

Returns code unchanged. Used as the baseline to measure unperturbed performance.

## rename_symbols (`python_rename_symbols.py`)

Replaces selected symbol types with opaque placeholders using `libcst`.

- Functions: `calculate_total` -> `func_0`, `process_data` -> `func_1`, ...
- Classes: `MyParser` -> `cls_0`, `DataLoader` -> `cls_1`, ...
- Parameters (optional): `left`, `right` -> `arg_0`, `arg_1`, ...
- All in-file references (calls, attribute access) are updated consistently
- Names starting with `_` or `__` are skipped (private/dunder)
- Output is validated with `ast.parse()` to guarantee syntactic correctness
- Stats report counts and mapping metadata (`renamed_function_map`, etc.)

## Adding a new perturbation

1. Create a class with `name: str` attribute and `apply(PerturbationInput) -> PerturbationResult`
2. Accept constructor kwargs from Hydra (name, any config flags)
3. Add a yaml in `configs/perturbation/`
4. Never depend on dataset-specific sample types -- work only with `PerturbationInput.code`
