"""Register dated OpenAI model slugs with litellm's cost map.

litellm publishes prices under base names (`gpt-5.4-nano`) but the API often
returns dated slugs (`gpt-5.4-nano-2026-03-17`). Without the alias,
mini-swe-agent's cost tracking crashes or silently reports $0.

`register_model_cost(slug)` auto-aliases any slug of shape `<base>-YYYY-MM-DD`
to the pricing of `<base>` — no hand-maintained registry needed.
"""
import logging
import re

import litellm

logger = logging.getLogger(__name__)

_DATED_SUFFIX_RE = re.compile(r"^(.+)-\d{4}-\d{2}-\d{2}$")


def register_model_cost(slug: str) -> None:
    """If `slug` looks dated and its base is priced, copy the base's prices.

    Handles both bare (`gpt-5.4-nano-2026-03-17`) and prefixed
    (`openai/gpt-5.4-nano-2026-03-17`) slugs: litellm keys are typically
    unprefixed for OpenAI models, so we try the bare form as the base too.

    No-op if slug is already priced, doesn't match the dated pattern, or the
    base isn't in litellm's map. Safe to call repeatedly.
    """
    if slug in litellm.model_cost:
        return
    m = _DATED_SUFFIX_RE.match(slug)
    if not m:
        return
    base = m.group(1)
    for candidate in (base, base.split("/", 1)[-1]):
        if candidate in litellm.model_cost:
            litellm.model_cost[slug] = litellm.model_cost[candidate].copy()
            logger.debug("Aliased litellm cost: %s -> %s", slug, candidate)
            return
