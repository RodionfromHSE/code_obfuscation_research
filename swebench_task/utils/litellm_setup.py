"""Register dated OpenAI model slugs with litellm's cost map.

litellm knows gpt-5.4-nano but not gpt-5.4-nano-2026-03-17.
This copies pricing from the base name to dated variants so
mini-swe-agent's cost tracking works correctly.

Imported once at agent startup (runner.py).
"""
import litellm

_DATED_ALIASES = {
    "gpt-5.4-nano-2026-03-17": "gpt-5.4-nano",
    "gpt-5.4-mini-2026-03-17": "gpt-5.4-mini",
}


def register_model_costs() -> None:
    for dated, base in _DATED_ALIASES.items():
        if dated not in litellm.model_cost and base in litellm.model_cost:
            litellm.model_cost[dated] = litellm.model_cost[base].copy()
