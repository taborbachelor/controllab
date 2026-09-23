"""Optional AI engineering assistance (docs/CONTROL-LAB.md §10, Phase 8).

Nothing outside this package imports it, and importing it never needs an
AI SDK or an API key -- those are only touched when a model is actually
called. AI output is always a proposal in a file for an engineer; it
never runs control logic, never writes into scenarios/, and never
bypasses the candidate review gate (services/testing/candidates.py).
"""
from services.ai.provider import (
    DEFAULT_ANTHROPIC_MODEL,
    AIUnavailable,
    AnthropicProvider,
    Completion,
    Provider,
    ProviderError,
    get_provider,
)

__all__ = [
    "DEFAULT_ANTHROPIC_MODEL",
    "AIUnavailable",
    "AnthropicProvider",
    "Completion",
    "Provider",
    "ProviderError",
    "get_provider",
]
