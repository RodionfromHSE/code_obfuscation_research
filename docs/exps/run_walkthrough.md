# Run Pipeline Walkthrough

How inference experiments work end-to-end, with concrete examples from `default_run_noop.jsonl` and `default_run_rename_symbols.jsonl`.

## Pipeline overview

```
Dataset (HuggingFace)
  │
  ▼
CodeQASample { sample_id, code: CodeArtifact, question, answer }
  │
  ├─ perturbation.apply(code)  →  perturbed CodeArtifact
  │
  ▼
task.build_request(sample, perturbed_code)  →  ModelRequest { messages }
  │
  ▼
LLMRuntime.invoke(request)  →  ModelResponse { text }
  │
  ▼
RunRecord { request_messages, response_text, reference_text }  →  JSONL
```

## Prompt template

**System message** (hardcoded in `tasks/codeqa.py`):

> You are a code comprehension assistant. Given a code snippet and a question about it, provide a concise and accurate answer.

**User message** (built from sample + perturbed code):

```
Code:
\```{language}
{perturbed_code_text}
\```

Question: {sample.question}
```

The model is `gpt-5.4-nano-2026-03-17`. No structured output — raw text completion.

---

## Sample 1 — `codeqa_0`

<details>
<summary><b>Code snippet</b> (original)</summary>

```python
def expose_request(func):
	if (not python.callable(func)):
		raise TypeError('func 	must 	be 	callable')
	if isinstance(func, types.UnboundMethodType):
		setattr(func.im_func, '_pyamf_expose_request', True)
	else:
		setattr(func, '_pyamf_expose_request', True)
	return func
```

**Question:** What adds an expose_request flag to the underlying callable?
**Reference answer:** a decorator

</details>

<details>
<summary><b>Chat — noop (no perturbation)</b></summary>

**→ System:**
> You are a code comprehension assistant. Given a code snippet and a question about it, provide a concise and accurate answer.

**→ User:**
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

**← Model response:**
> The decorator `expose_request` sets an attribute on the callable it receives:
>
> - It calls `setattr(..., '_pyamf_expose_request', True)`.
> - For `types.UnboundMethodType`, it does it on the underlying function via `func.im_func`.
> - Otherwise, it sets it directly on `func`.

</details>

<details>
<summary><b>Chat — rename_symbols perturbation</b></summary>

Perturbation stats: `renamed_functions: 1, renamed_classes: 0`

**→ System:**
> You are a code comprehension assistant. Given a code snippet and a question about it, provide a concise and accurate answer.

**→ User:**
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

Note: `expose_request` → `func_0` (the function name was obfuscated).

**← Model response:**
> The decorator `func_0` adds the `_pyamf_expose_request` attribute (the "expose_request" flag) to the underlying callable by calling `setattr(...)`:
>
> - If `func` is a `types.UnboundMethodType`, it sets it on `func.im_func`:
>   ```python
>   setattr(func.im_func, '_pyamf_expose_request', True)
>   ```
> - Otherwise, it sets it directly on `func`:
>   ```python
>   setattr(func, '_pyamf_expose_request', True)
>   ```

</details>

---

## Sample 2 — `codeqa_2`

<details>
<summary><b>Code snippet</b> (original)</summary>

```python
def browser(honor_time=True, max_time=2, mobile_browser=False, user_agent=None, use_robust_parser=False, verify_ssl_certificates=True):
	from calibre.utils.browser import Browser
	if use_robust_parser:
		import mechanize
		opener = Browser(factory=mechanize.RobustFactory(), verify_ssl=verify_ssl_certificates)
	else:
		opener = Browser(verify_ssl=verify_ssl_certificates)
	opener.set_handle_refresh(True, max_time=max_time, honor_time=honor_time)
	opener.set_handle_robots(False)
	if (user_agent is None):
		user_agent = (USER_AGENT_MOBILE if mobile_browser else USER_AGENT)
	opener.addheaders = [('User-agent', user_agent)]
	proxies = get_proxies()
	to_add = {}
	http_proxy = proxies.get('http', None)
	if http_proxy:
		to_add['http'] = http_proxy
	https_proxy = proxies.get('https', None)
	if https_proxy:
		to_add['https'] = https_proxy
	if to_add:
		opener.set_proxies(to_add)
	return opener
```

**Question:** What does the code create?
**Reference answer:** a mechanize browser for web scraping

</details>

<details>
<summary><b>Chat — noop (no perturbation)</b></summary>

**→ System:**
> You are a code comprehension assistant. Given a code snippet and a question about it, provide a concise and accurate answer.

**→ User:**
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

**← Model response:**
> The function `browser(...)` creates and returns a configured **`Browser` object** from `calibre.utils.browser`.
>
> It sets refresh-handling behavior, disables robots handling, applies a `User-agent` (based on `mobile_browser` unless `user_agent` is provided), optionally configures HTTP/HTTPS proxies, and optionally uses a robust `mechanize` factory and SSL certificate verification.

</details>

<details>
<summary><b>Chat — rename_symbols perturbation</b></summary>

Perturbation stats: `renamed_functions: 1, renamed_classes: 0`

**→ System:**
> You are a code comprehension assistant. Given a code snippet and a question about it, provide a concise and accurate answer.

**→ User:**
> Code:
> ```python
> def func_0(honor_time=True, max_time=2, mobile_browser=False, user_agent=None, use_robust_parser=False, verify_ssl_certificates=True):
> 	from calibre.utils.browser import Browser
> 	...
> 	return opener
> ```
>
> Question: What does the code create ?

Note: `browser` → `func_0`.

**← Model response:**
> The function `func_0(...)` creates and returns a configured **Calibre `Browser` instance** (stored in `opener`). It sets options like refresh handling, robots handling, a User-Agent header (based on `mobile_browser` unless `user_agent` is provided), SSL verification, and proxy settings from `get_proxies()` (HTTP/HTTPS). If `use_robust_parser` is `True`, it uses a `mechanize.RobustFactory()` for the browser.

</details>

---

## Sample 3 — `codeqa_3`

<details>
<summary><b>Code snippet</b> (original)</summary>

```python
@task
def docker_init(ctx):
	import platform
	print 'You	will	be	asked	for	your	sudo	password	to	continue...'
	if (platform.system() == 'Darwin'):
		ctx.run('sudo	ifconfig	lo0	alias	192.168.168.167')
	else:
		print 'Your	system	is	not	recognized,	you	will	have	to	setup	docker	manually'
```

**Question:** What does this function do?
**Reference answer:** Initial docker setup

</details>

<details>
<summary><b>Chat — noop (no perturbation)</b></summary>

**→ System:**
> You are a code comprehension assistant. Given a code snippet and a question about it, provide a concise and accurate answer.

**→ User:**
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

**← Model response:**
> The `docker_init` task prints a message telling the user they'll be prompted for their sudo password, then checks the OS:
>
> - If the system is **macOS** (`platform.system() == 'Darwin'`), it runs a sudo command to configure a loopback network alias:
>   `sudo ifconfig lo0 alias 192.168.168.167`
> - Otherwise, it prints that the system isn't recognized and that the user must set up Docker manually.

</details>

<details>
<summary><b>Chat — rename_symbols perturbation</b></summary>

Perturbation stats: (none — `@task` decorator prevented rename)

**→ System:**
> You are a code comprehension assistant. Given a code snippet and a question about it, provide a concise and accurate answer.

**→ User:**
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

Note: code is identical — the decorator-based function wasn't renamed.

**← Model response:**
> The `docker_init` task prints a message telling the user they'll be prompted for their sudo password, then checks the OS:
>
> - If the system is **macOS** (`platform.system() == 'Darwin'`), it runs a sudo command to configure a loopback network alias:
>   `sudo ifconfig lo0 alias 192.168.168.167`
> - Otherwise, it prints that the system isn't recognized and that the user must set up Docker manually.

</details>
