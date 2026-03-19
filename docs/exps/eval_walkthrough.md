# Eval Pipeline Walkthrough

How the evaluation pipeline judges model answers, with concrete examples from `default_eval_results.jsonl`.

## Pipeline overview

```
RunRecord JSONL files (from run pipeline)
  │
  ▼
_records_to_eval_cases()  →  EvalCase { input_text, actual_output, expected_output }
  │
  ▼
DeepEval GEval metric  →  judge model scores 0 or 1
  │
  ▼
CorrectnessResult { is_correct, score, reason }  →  JSONL
```

## How eval cases are built

From each `RunRecord`, the eval pipeline extracts:

| EvalCase field     | Source                                                        |
|--------------------|---------------------------------------------------------------|
| `input_text`       | The **user message** from `request_messages` (code + question) |
| `actual_output`    | `response_text` (task model's answer)                          |
| `expected_output`  | `reference_text` (ground truth from dataset)                   |

## Judge model configuration

- **Model:** `gpt-5.4-mini-2026-03-17`
- **Metric:** DeepEval `GEval` with `strict_mode=True` (binary 0 or 1)
- **Criteria:** "Is the actual output factually correct given the expected output? Answer yes (1) or no (0)."
- **Evaluation steps** (from `configs/evaluator/deepeval_correctness.yaml`):
  1. Does the actual output answer the question correctly given the expected output?
  2. The answer must be factually consistent with the expected output
  3. Minor phrasing differences are acceptable if the meaning is the same
- **Threshold:** 0.5

## What the judge model sees

DeepEval's GEval constructs its own prompt internally. It receives three evaluation parameters via `LLMTestCase`:

- **INPUT** — the full user message (code block + question)
- **ACTUAL_OUTPUT** — the task model's answer
- **EXPECTED_OUTPUT** — the ground truth answer

The judge then applies the criteria and evaluation steps to produce a score (0 or 1) and a free-text reason.

---

## Sample 1 — `codeqa_0`

**Question:** What adds an expose_request flag to the underlying callable?
**Reference answer:** a decorator

### noop — **Incorrect** (score: 0)

<details>
<summary><b>Run data fed to judge</b></summary>

**INPUT** (the full user message from the run):
> Code:
> ```python
> def expose_request(func):
> 	if (not python.callable(func)):
> 		raise TypeError('func 	must 	be 	callable')
> 	if isinstance(func, types.UnboundMethodType):
> 		setattr(func.im_func, '_pyamf_expose_request', True)
> 	else:
> 		setattr(func, '_pyamf_expose_request', True)
> 	return func
> ```
>
> Question: What adds an expose_request flag to the underlying callable ?

**ACTUAL_OUTPUT** (task model's answer):
> The decorator `expose_request` sets an attribute on the callable it receives:
>
> - It calls `setattr(..., '_pyamf_expose_request', True)`.
> - For `types.UnboundMethodType`, it does it on the underlying function via `func.im_func`.
> - Otherwise, it sets it directly on `func`.

**EXPECTED_OUTPUT** (ground truth):
> a decorator

</details>

<details>
<summary><b>Judge verdict</b></summary>

- **Score:** 0
- **Is correct:** false
- **Reason:** The Input asks what adds an expose_request flag to the underlying callable, and the Expected Output says "a decorator". The Actual Output describes how expose_request uses setattr on func or func.im_func, but it does not give the expected concise answer.

</details>

### rename_symbols — **Incorrect** (score: 0)

<details>
<summary><b>Run data fed to judge</b></summary>

**INPUT** (the full user message from the run):
> Code:
> ```python
> def func_0(func):
> 	if (not python.callable(func)):
> 		raise TypeError('func 	must 	be 	callable')
> 	if isinstance(func, types.UnboundMethodType):
> 		setattr(func.im_func, '_pyamf_expose_request', True)
> 	else:
> 		setattr(func, '_pyamf_expose_request', True)
> 	return func
> ```
>
> Question: What adds an expose_request flag to the underlying callable ?

Note: `expose_request` → `func_0` (function name obfuscated).

**ACTUAL_OUTPUT** (task model's answer):
> The decorator `func_0` adds the `_pyamf_expose_request` attribute (the "expose_request" flag) to the underlying callable by calling `setattr(...)`:
>
> - If `func` is a `types.UnboundMethodType`, it sets it on `func.im_func`
> - Otherwise, it sets it directly on `func`

**EXPECTED_OUTPUT** (ground truth):
> a decorator

</details>

<details>
<summary><b>Judge verdict</b></summary>

- **Score:** 0
- **Is correct:** false
- **Reason:** Input asks what adds an expose_request flag to the underlying callable; the expected output says "a decorator," while the actual output names func_0 and explains setattr behavior instead of giving that concise answer.

</details>

---

## Sample 2 — `codeqa_2`

**Question:** What does the code create?
**Reference answer:** a mechanize browser for web scraping

### noop — **Correct** (score: 1)

<details>
<summary><b>Run data fed to judge</b></summary>

**INPUT** (the full user message from the run):
> Code:
> ```python
> def browser(honor_time=True, max_time=2, mobile_browser=False, user_agent=None, use_robust_parser=False, verify_ssl_certificates=True):
> 	from calibre.utils.browser import Browser
> 	if use_robust_parser:
> 		import mechanize
> 		opener = Browser(factory=mechanize.RobustFactory(), verify_ssl=verify_ssl_certificates)
> 	else:
> 		opener = Browser(verify_ssl=verify_ssl_certificates)
> 	opener.set_handle_refresh(True, max_time=max_time, honor_time=honor_time)
> 	opener.set_handle_robots(False)
> 	if (user_agent is None):
> 		user_agent = (USER_AGENT_MOBILE if mobile_browser else USER_AGENT)
> 	opener.addheaders = [('User-agent', user_agent)]
> 	proxies = get_proxies()
> 	to_add = {}
> 	http_proxy = proxies.get('http', None)
> 	if http_proxy:
> 		to_add['http'] = http_proxy
> 	https_proxy = proxies.get('https', None)
> 	if https_proxy:
> 		to_add['https'] = https_proxy
> 	if to_add:
> 		opener.set_proxies(to_add)
> 	return opener
> ```
>
> Question: What does the code create ?

**ACTUAL_OUTPUT** (task model's answer):
> The function `browser(...)` creates and returns a configured **`Browser` object** from `calibre.utils.browser`.
>
> It sets refresh-handling behavior, disables robots handling, applies a `User-agent` (based on `mobile_browser` unless `user_agent` is provided), optionally configures HTTP/HTTPS proxies, and optionally uses a robust `mechanize` factory and SSL certificate verification.

**EXPECTED_OUTPUT** (ground truth):
> a mechanize browser for web scraping

</details>

<details>
<summary><b>Judge verdict</b></summary>

- **Score:** 1
- **Is correct:** true
- **Reason:** Input asks what the code creates; Actual Output says it creates a configured Browser object from calibre.utils.browser, which matches Expected Output's mechanize browser for web scraping. The added details about refresh, robots, user-agent, proxies, and SSL are consistent with the code.

</details>

### rename_symbols — **Correct** (score: 1)

<details>
<summary><b>Run data fed to judge</b></summary>

**INPUT** (the full user message from the run):
> Code:
> ```python
> def func_0(honor_time=True, max_time=2, mobile_browser=False, user_agent=None, use_robust_parser=False, verify_ssl_certificates=True):
> 	from calibre.utils.browser import Browser
> 	...
> 	return opener
> ```
>
> Question: What does the code create ?

Note: `browser` → `func_0` (function name obfuscated).

**ACTUAL_OUTPUT** (task model's answer):
> The function `func_0(...)` creates and returns a configured **Calibre `Browser` instance** (stored in `opener`). It sets options like refresh handling, robots handling, a User-Agent header (based on `mobile_browser` unless `user_agent` is provided), SSL verification, and proxy settings from `get_proxies()` (HTTP/HTTPS). If `use_robust_parser` is `True`, it uses a `mechanize.RobustFactory()` for the browser.

**EXPECTED_OUTPUT** (ground truth):
> a mechanize browser for web scraping

</details>

<details>
<summary><b>Judge verdict</b></summary>

- **Score:** 1
- **Is correct:** true
- **Reason:** Input code creates and returns an opener Browser object; Actual Output says it is a configured Calibre Browser instance for web scraping with User-Agent, SSL, and proxy settings; Expected Output says a mechanize browser for web scraping, which matches.

</details>

---

## Sample 3 — `codeqa_3`

**Question:** What does this function do?
**Reference answer:** Initial docker setup

### noop — **Incorrect** (score: 0)

<details>
<summary><b>Run data fed to judge</b></summary>

**INPUT** (the full user message from the run):
> Code:
> ```python
> @task
> def docker_init(ctx):
> 	import platform
> 	print 'You	will	be	asked	for	your	sudo	password	to	continue...'
> 	if (platform.system() == 'Darwin'):
> 		ctx.run('sudo	ifconfig	lo0	alias	192.168.168.167')
> 	else:
> 		print 'Your	system	is	not	recognized,	you	will	have	to	setup	docker	manually'
> ```
>
> Question: What does this function do?

**ACTUAL_OUTPUT** (task model's answer):
> The `docker_init` task prints a message telling the user they'll be prompted for their sudo password, then checks the OS:
>
> - If the system is **macOS** (`platform.system() == 'Darwin'`), it runs a sudo command to configure a loopback network alias:
>   `sudo ifconfig lo0 alias 192.168.168.167`
> - Otherwise, it prints that the system isn't recognized and that the user must set up Docker manually.

**EXPECTED_OUTPUT** (ground truth):
> Initial docker setup

</details>

<details>
<summary><b>Judge verdict</b></summary>

- **Score:** 0
- **Is correct:** false
- **Reason:** Input asks what the `docker_init` function does, and the expected output is only "Initial docker setup". The actual output describes sudo prompt, macOS loopback alias setup, and a manual setup fallback, which is more detailed and not the same as the expected output.

</details>

### rename_symbols — **Incorrect** (score: 0)

<details>
<summary><b>Run data fed to judge</b></summary>

**INPUT** (the full user message from the run):
> Code:
> ```python
> @task
> def docker_init(ctx):
> 	import platform
> 	print 'You	will	be	asked	for	your	sudo	password	to	continue...'
> 	if (platform.system() == 'Darwin'):
> 		ctx.run('sudo	ifconfig	lo0	alias	192.168.168.167')
> 	else:
> 		print 'Your	system	is	not	recognized,	you	will	have	to	setup	docker	manually'
> ```
>
> Question: What does this function do?

Note: code is identical — the `@task` decorator prevented the rename perturbation from firing.

**ACTUAL_OUTPUT** (task model's answer):
> The `docker_init` task prints a message telling the user they'll be prompted for their sudo password, then checks the OS:
>
> - If the system is **macOS** (`platform.system() == 'Darwin'`), it runs a sudo command to configure a loopback network alias:
>   `sudo ifconfig lo0 alias 192.168.168.167`
> - Otherwise, it prints that the system isn't recognized and that the user must set up Docker manually.

**EXPECTED_OUTPUT** (ground truth):
> Initial docker setup

</details>

<details>
<summary><b>Judge verdict</b></summary>

- **Score:** 0
- **Is correct:** false
- **Reason:** Input asks what the function does, and the expected output is only "Initial docker setup". The actual output describes sudo password prompt, macOS loopback alias setup, and a manual setup fallback, which is more specific and does not match the expected output exactly.

</details>
