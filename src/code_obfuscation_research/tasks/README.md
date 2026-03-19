# tasks/

Task definitions implement the `TaskDefinition` protocol. Each task knows how to build a prompt, parse the model's response, and create an eval case.

## CodeQA task (`codeqa.py`)

Code question-answering over Python snippets.

**Prompt template:**

```
System: You are a code comprehension assistant. Given a code snippet
        and a question about it, provide a concise and accurate answer.

User:   Code:
        ```python
        {code}                    <-- this is the (possibly perturbed) code
        ```

        Question: {question}      <-- from the dataset
```

**Expected output:** the model's free-text answer, stripped of whitespace.

**Reference:** the `answer` field from `CodeQASample` (auto-derived from code comments in the CodeQA dataset -- can be noisy).

**Eval case:** the judge sees `(input=question, actual_output=prediction, expected_output=reference)`. The judge never sees the original or perturbed code.

## Adding a new task

1. Create a class implementing `TaskDefinition[YourSampleT]`
2. Implement `build_request`, `parse_prediction`, `build_reference`, `build_eval_case`
3. Add a yaml in `configs/task/`
4. If needed, create a new sample type extending `CodeTaskSample` and a matching `DatasetAdapter`
