"""The provider abstraction (docs/CONTROL-LAB.md §10, Phase 8 step 2).

Everything AI in ControlLab goes through one small interface: give a
system prompt, a user message, a JSON schema, and an output-token cap;
get back JSON that matches the schema, plus usage. Generation and
analysis are both built on that one call, so adding a provider means
implementing `complete_json` and registering it -- nothing in Control,
Simulation, Testing, or Protocols knows providers exist (enforced by
tests/unit/test_ai_boundary.py).

Anthropic is the initial provider. Rules it follows, from the Phase 8
decisions:

- **Optional.** The SDK is imported lazily, inside the call, and only
  ships with the `[ai]` extra (`pip install -e ".[ai]"`). Importing this
  module, or anything else in ControlLab, never needs it.
- **Credentials only from ANTHROPIC_API_KEY**, read at call time and
  passed explicitly to a client that lives for one call. The provider
  object never stores the key, never logs it, and nothing it returns
  contains it. The SDK's other credential sources (auth tokens, CLI
  profiles) are deliberately not used, so there is exactly one place a
  key can come from. No key means a clear AIUnavailable error -- and
  only for AI features; nothing else ever asks for one.
- **Bounded output**: `max_tokens` is always passed and always a hard
  limit (services/ai/limits.py). Hitting it is an error, not a silently
  truncated answer.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"
API_KEY_ENV = "ANTHROPIC_API_KEY"


class AIUnavailable(RuntimeError):
    """AI can't run here: the SDK isn't installed or the key isn't set.
    Never raised by non-AI code paths."""


class ProviderError(RuntimeError):
    """The provider was reached but didn't produce a usable answer
    (declined, truncated, rate-limited, invalid JSON, ...). Messages never
    include credentials."""


@dataclass(frozen=True)
class Completion:
    data: dict
    model: str
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    name: str

    def complete_json(self, *, system: str, user: str, schema: dict, max_tokens: int) -> Completion: ...


class AnthropicProvider:
    """Claude via the official `anthropic` SDK, Messages API, structured
    JSON output. Server-side refusal fallback is on (`fallbacks="default"`),
    per Anthropic's guidance for Claude Opus 5: a declined request is
    re-run on the recommended fallback model instead of failing; a decline
    that survives the fallback is reported as a ProviderError."""

    name = "anthropic"

    def __init__(self, model: str = DEFAULT_ANTHROPIC_MODEL, timeout_s: float = 300.0) -> None:
        self.model = model
        self.timeout_s = timeout_s

    def __repr__(self) -> str:
        return f"AnthropicProvider(model={self.model!r})"

    def complete_json(self, *, system: str, user: str, schema: dict, max_tokens: int) -> Completion:
        try:
            import anthropic
        except ImportError:
            raise AIUnavailable(
                "the Anthropic SDK isn't installed -- AI features are optional: pip install -e \".[ai]\""
            ) from None
        key = os.environ.get(API_KEY_ENV)
        if not key:
            raise AIUnavailable(f"{API_KEY_ENV} is not set -- it's only needed for AI features")

        client = anthropic.Anthropic(api_key=key, timeout=self.timeout_s, max_retries=2)
        del key  # the client holds it for this one call only
        try:
            response = client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            raise ProviderError(f"authentication failed -- check {API_KEY_ENV}") from None
        except anthropic.PermissionDeniedError:
            raise ProviderError("the API key lacks permission for this request") from None
        except anthropic.RateLimitError:
            raise ProviderError("rate limited by the provider -- try again later") from None
        except anthropic.BadRequestError as e:
            raise ProviderError(f"the provider rejected the request: {e.message}") from None
        except anthropic.APIStatusError as e:
            raise ProviderError(f"provider error (HTTP {e.status_code})") from None
        except anthropic.APIConnectionError:
            raise ProviderError("couldn't reach the provider (network)") from None
        finally:
            client.close()

        if response.stop_reason == "refusal":
            raise ProviderError("the model declined the request")
        if response.stop_reason == "max_tokens":
            raise ProviderError(f"the answer hit the {max_tokens}-token output limit and was cut off")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise ProviderError("the response contained no text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise ProviderError("the response wasn't valid JSON") from None
        return Completion(
            data=data,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


PROVIDERS = {AnthropicProvider.name: AnthropicProvider}


def get_provider(name: str = "anthropic", **options) -> Provider:
    try:
        return PROVIDERS[name](**options)
    except KeyError:
        raise ValueError(f"unknown AI provider {name!r} (known: {', '.join(sorted(PROVIDERS))})") from None
