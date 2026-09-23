"""The AI provider layer's guarantees (Phase 8), with no network and no
real SDK call: a fake `anthropic` module stands in for the SDK so the
exact request is inspectable, and a subprocess proves ControlLab works
with the SDK absent altogether."""
import subprocess
import sys
import types
from pathlib import Path

import pytest

from services.ai.provider import AIUnavailable, AnthropicProvider, ProviderError, get_provider

REPO = Path(__file__).resolve().parents[2]
FAKE_KEY = "sk-ant-test-THIS-MUST-NEVER-BE-PERSISTED"
CORE = ["control", "simulation", "testing", "telemetry", "protocols", "visualization"]


# ---- boundaries -----------------------------------------------------------------

@pytest.mark.parametrize("package", CORE)
def test_core_layers_never_import_ai_or_an_ai_sdk(package):
    for path in sorted((REPO / "services" / package).glob("*.py")):
        imports = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip().startswith(("import ", "from "))]
        bad = [l for l in imports if "services.ai" in l or l.split()[1].split(".")[0] == "anthropic"]
        assert not bad, f"{path.name}: {bad}"


def test_controllab_runs_with_no_ai_sdk_installed():
    """Block the SDK entirely, then import the AI package and run a real
    scenario. Only an actual model call may fail -- and it fails clearly."""
    code = """
import sys
sys.modules["anthropic"] = None  # import anthropic -> ImportError
from pathlib import Path
import services.ai
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario
assert run_scenario(Scenario.load(Path("scenarios/startup/normal_start.yaml"))).passed
try:
    services.ai.AnthropicProvider().complete_json(system="s", user="u", schema={}, max_tokens=10)
except services.ai.AIUnavailable as e:
    print("AIUnavailable:", e)
"""
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "AIUnavailable: the Anthropic SDK isn't installed" in out.stdout


def test_no_api_key_is_needed_until_a_model_is_called(monkeypatch):
    # The fake SDK, so this checks the key handling whether or not the optional
    # [ai] extra is installed (it isn't in CI; the SDK check would answer first).
    monkeypatch.setitem(sys.modules, "anthropic", fake_sdk()[0])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = get_provider("anthropic")  # constructing it needs no key
    with pytest.raises(AIUnavailable, match="ANTHROPIC_API_KEY is not set"):
        provider.complete_json(system="s", user="u", schema={}, max_tokens=10)


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="unknown AI provider"):
        get_provider("oracle")


# ---- the request, against a fake SDK ---------------------------------------------

class _Err(Exception):
    def __init__(self, message="", status_code=500):
        super().__init__(message)
        self.message, self.status_code = message, status_code


def fake_sdk(response=None, raises=None):
    calls = {}
    sdk = types.ModuleType("anthropic")
    for name in ("AuthenticationError", "PermissionDeniedError", "RateLimitError", "BadRequestError",
                 "APIStatusError", "APIConnectionError"):
        setattr(sdk, name, type(name, (_Err,), {}))

    class Anthropic:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            calls["request"] = kwargs
            if raises:
                raise getattr(sdk, raises)("boom " + calls["client"]["api_key"][:0])
            return response

        def close(self):
            calls["closed"] = True

    sdk.Anthropic = Anthropic
    return sdk, calls


def response(text='{"ok": true}', stop_reason="end_turn"):
    return types.SimpleNamespace(
        stop_reason=stop_reason, model="claude-opus-5",
        content=[types.SimpleNamespace(type="thinking", thinking=""), types.SimpleNamespace(type="text", text=text)],
        usage=types.SimpleNamespace(input_tokens=120, output_tokens=40),
    )


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)


def test_the_request_is_bounded_structured_and_keyed_only_from_the_env(monkeypatch, with_key):
    sdk, calls = fake_sdk(response())
    monkeypatch.setitem(sys.modules, "anthropic", sdk)
    provider = AnthropicProvider()
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    out = provider.complete_json(system="SYS", user="USER", schema=schema, max_tokens=1234)

    assert out.data == {"ok": True} and (out.input_tokens, out.output_tokens) == (120, 40)
    assert calls["client"]["api_key"] == FAKE_KEY
    req = calls["request"]
    assert (req["model"], req["max_tokens"], req["system"]) == ("claude-opus-5", 1234, "SYS")
    assert req["messages"] == [{"role": "user", "content": "USER"}]
    assert req["output_config"] == {"format": {"type": "json_schema", "schema": schema}}
    assert (req["fallbacks"], req["betas"]) == ("default", ["server-side-fallback-2026-07-01"])
    assert calls["closed"]
    # the key never outlives the call
    assert FAKE_KEY not in repr(provider) and FAKE_KEY not in repr(vars(provider)) and FAKE_KEY not in repr(out)


@pytest.mark.parametrize(
    "resp,match",
    [
        (response(stop_reason="refusal"), "declined"),
        (response(stop_reason="max_tokens"), "output limit"),
        (response(text="not json"), "valid JSON"),
    ],
)
def test_unusable_answers_are_errors_not_silent_output(monkeypatch, with_key, resp, match):
    sdk, _ = fake_sdk(resp)
    monkeypatch.setitem(sys.modules, "anthropic", sdk)
    with pytest.raises(ProviderError, match=match):
        AnthropicProvider().complete_json(system="s", user="u", schema={}, max_tokens=10)


@pytest.mark.parametrize("error", ["AuthenticationError", "RateLimitError", "APIConnectionError", "APIStatusError"])
def test_sdk_errors_map_to_provider_errors_without_leaking_the_key(monkeypatch, with_key, error):
    sdk, _ = fake_sdk(raises=error)
    monkeypatch.setitem(sys.modules, "anthropic", sdk)
    with pytest.raises(ProviderError) as e:
        AnthropicProvider().complete_json(system="s", user="u", schema={}, max_tokens=10)
    assert FAKE_KEY not in str(e.value)
