"""Unit tests for the native Anthropic Claude Code -> Copilot request bridge.

Covers each of the four transforms, that non-bridge paths are left untouched, and
that a mutated body forces a content-length recompute in the proxy forward path.
"""
import json

import pytest

import proxy
from ctc import contract
from ctc.routing import anthropic_bridge

BILLABLE_HOST = contract.BILLABLE_HOST
IDENTITY = contract.COPILOT_API_IDENTITY_HEADERS


# --------------------------------------------------------------------------
# is_bridge_request — scoping
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "host,method,path,expected",
    [
        (BILLABLE_HOST, "POST", "/v1/messages", True),
        (BILLABLE_HOST, "POST", "/v1/messages?beta=true", True),
        (BILLABLE_HOST, "post", "/v1/messages", True),
        # wrong method / path / host — untouched
        (BILLABLE_HOST, "GET", "/v1/messages", False),
        (BILLABLE_HOST, "POST", "/chat/completions", False),
        (BILLABLE_HOST, "POST", "/responses", False),
        (BILLABLE_HOST, "POST", "/v1/messages/count_tokens", False),
        (BILLABLE_HOST, "POST", "/models/session", False),
        ("api.github.com", "POST", "/v1/messages", False),
        ("api.example.ghe.com", "POST", "/v1/messages", False),
    ],
)
def test_is_bridge_request(host, method, path, expected):
    assert anthropic_bridge.is_bridge_request(host, method, path) is expected


# --------------------------------------------------------------------------
# Transform 1: client identity injection
# --------------------------------------------------------------------------
def test_identity_injected_and_overrides_client_values():
    fwd = {"user-agent": "claude-cli/1.2.3", "accept": "*/*"}
    out = anthropic_bridge.transform_request_headers(fwd)
    assert out["copilot-integration-id"] == "copilot-developer-cli"
    assert out["editor-version"] == "copilot/1.0.63"
    assert out["user-agent"] == "GitHubCopilotChat/copilot/1.0.63"
    assert out["accept"] == "*/*"  # unrelated headers preserved


# --------------------------------------------------------------------------
# Transform 2: anthropic-beta filter
# --------------------------------------------------------------------------
def test_beta_dropped_by_default_empty_allowlist():
    fwd = {"anthropic-beta": "advisor-tool-2026-03-01,mid-conversation-system-2026-04-07"}
    out = anthropic_bridge.transform_request_headers(fwd, beta_allow=frozenset())
    assert "anthropic-beta" not in out


def test_beta_dropped_regardless_of_header_casing():
    fwd = {"Anthropic-Beta": "advisor-tool-2026-03-01"}
    out = anthropic_bridge.transform_request_headers(fwd, beta_allow=frozenset())
    assert not any(k.lower() == "anthropic-beta" for k in out)


def test_beta_allowlist_keeps_only_allowed_values():
    fwd = {"anthropic-beta": "keep-me,drop-me"}
    out = anthropic_bridge.transform_request_headers(fwd, beta_allow=frozenset({"keep-me"}))
    assert out["anthropic-beta"] == "keep-me"


def test_no_beta_header_is_noop():
    fwd = {"accept": "*/*"}
    out = anthropic_bridge.transform_request_headers(fwd)
    assert "anthropic-beta" not in out


def test_output_config_stripped():
    body = json.dumps({
        "model": "claude-haiku-4.5",
        "output_config": {"reasoning_effort": "high"},
        "messages": [],
    }).encode()
    out = anthropic_bridge.transform_request_body(body)
    obj = json.loads(out)
    assert "output_config" not in obj
    assert obj["model"] == "claude-haiku-4.5"  # rest preserved


# --------------------------------------------------------------------------
# Transform 4: thinking coercion
# --------------------------------------------------------------------------
def test_thinking_adaptive_coerced_to_disabled_by_default():
    body = json.dumps({"thinking": {"type": "adaptive"}, "messages": []}).encode()
    out = anthropic_bridge.transform_request_body(body)
    assert json.loads(out)["thinking"] == {"type": "disabled"}


def test_thinking_adaptive_coerced_to_enabled_when_configured():
    body = json.dumps({"thinking": {"type": "adaptive"}}).encode()
    out = anthropic_bridge.transform_request_body(
        body, thinking_mode="enabled", thinking_budget=4096)
    assert json.loads(out)["thinking"] == {"type": "enabled", "budget_tokens": 4096}


def test_thinking_already_valid_is_preserved():
    for th in ({"type": "disabled"}, {"type": "enabled", "budget_tokens": 2048}):
        body = json.dumps({"thinking": th}).encode()
        out = anthropic_bridge.transform_request_body(body)
        assert json.loads(out)["thinking"] == th


SONNET_55_MODELS = ("claude-sonnet-5.5", "claude-sonnet-5-5", "claude-sonnet-5-5-20260901", "Claude-Sonnet-5.5")


@pytest.mark.parametrize("model", SONNET_55_MODELS)
def test_thinking_between_tools_passes_through_for_sonnet_55(model):
    """Sonnet 5.5 rejects {type:"disabled"}; a client-sent between_tools must
    reach Copilot untouched (and without a needless reserialize)."""
    body = json.dumps({"model": model, "thinking": {"type": "between_tools"}}).encode()
    out = anthropic_bridge.transform_request_body(body)
    assert out == body


@pytest.mark.parametrize("model", SONNET_55_MODELS)
def test_thinking_adaptive_coerced_to_between_tools_for_sonnet_55(model):
    body = json.dumps({"model": model, "thinking": {"type": "adaptive"}}).encode()
    out = anthropic_bridge.transform_request_body(body)
    assert json.loads(out)["thinking"] == {"type": "between_tools"}


def test_thinking_disabled_rewritten_to_between_tools_for_sonnet_55():
    body = json.dumps({"model": "claude-sonnet-5.5", "thinking": {"type": "disabled"}}).encode()
    out = anthropic_bridge.transform_request_body(body)
    assert json.loads(out)["thinking"] == {"type": "between_tools"}


@pytest.mark.parametrize("model", ("claude-opus-4.6", "claude-haiku-4.5", None))
def test_thinking_between_tools_rewritten_to_disabled_for_other_models(model):
    body = json.dumps({"model": model, "thinking": {"type": "between_tools"}}).encode()
    out = anthropic_bridge.transform_request_body(body)
    assert json.loads(out)["thinking"] == {"type": "disabled"}


def test_thinking_enabled_still_honoured_for_sonnet_55():
    body = json.dumps({"model": "claude-sonnet-5.5", "thinking": {"type": "adaptive"}}).encode()
    out = anthropic_bridge.transform_request_body(
        body, thinking_mode="enabled", thinking_budget=4096)
    assert json.loads(out)["thinking"] == {"type": "enabled", "budget_tokens": 4096}


def test_between_tools_models_configurable():
    body = json.dumps({"model": "claude-opus-6", "thinking": {"type": "adaptive"}}).encode()
    out = anthropic_bridge.transform_request_body(body, between_tools_models=("claude-opus-6",))
    assert json.loads(out)["thinking"] == {"type": "between_tools"}


OPUS_55_MODELS = ("claude-opus-5.5", "claude-opus-5-5", "claude-opus-5-5-20261001", "Claude-Opus-5.5")


@pytest.mark.parametrize("model", OPUS_55_MODELS)
def test_adaptive_and_output_config_pass_through_for_opus_55(model):
    """Opus 5.5 400s on disabled/between_tools/enabled and takes only adaptive,
    with output_config.effort controlling depth — forward both untouched."""
    body = json.dumps({"model": model, "thinking": {"type": "adaptive"},
                       "output_config": {"effort": "low"}}).encode()
    out = anthropic_bridge.transform_request_body(body)
    assert out == body


@pytest.mark.parametrize("th_type", ["disabled", "between_tools", "enabled", "future-mode"])
def test_non_adaptive_thinking_dropped_for_opus_55(th_type):
    body = json.dumps({"model": "claude-opus-5.5", "thinking": {"type": th_type},
                       "messages": []}).encode()
    out = json.loads(anthropic_bridge.transform_request_body(body))
    assert "thinking" not in out
    assert out["messages"] == []


def test_opus_55_ignores_global_enabled_mode():
    body = json.dumps({"model": "claude-opus-5.5", "thinking": {"type": "adaptive"}}).encode()
    out = anthropic_bridge.transform_request_body(body, thinking_mode="enabled")
    assert json.loads(out)["thinking"] == {"type": "adaptive"}


def test_context_management_stripped():
    body = json.dumps({"model": "claude-sonnet-5", "messages": [],
                       "context_management": {"edits": [{"type": "clear_thinking_20251015"}]}}).encode()
    obj = json.loads(anthropic_bridge.transform_request_body(body))
    assert "context_management" not in obj


def test_context_management_stripped_for_adaptive_models():
    body = json.dumps({"model": "claude-opus-5-5", "messages": [], "thinking": {"type": "adaptive"},
                       "context_management": {"edits": []}}).encode()
    obj = json.loads(anthropic_bridge.transform_request_body(body))
    assert "context_management" not in obj
    assert obj["thinking"] == {"type": "adaptive"}


def test_output_config_still_stripped_for_other_models():
    body = json.dumps({"model": "claude-opus-5", "thinking": {"type": "adaptive"},
                       "output_config": {"effort": "low"}}).encode()
    out = json.loads(anthropic_bridge.transform_request_body(body))
    assert "output_config" not in out
    assert out["thinking"] == {"type": "disabled"}


SONNET_5_MODELS = ("claude-sonnet-5", "claude-sonnet-5-20260801", "Claude-Sonnet-5")


@pytest.mark.parametrize("model", SONNET_5_MODELS)
def test_adaptive_and_output_config_pass_through_for_sonnet_5(model):
    """Copilot lists adaptive_thinking + reasoning_effort for Sonnet 5; forward
    them so ctc claude thinks like native Claude Code."""
    body = json.dumps({"model": model, "thinking": {"type": "adaptive", "display": "omitted"},
                       "output_config": {"effort": "medium"}}).encode()
    assert anthropic_bridge.transform_request_body(body) == body


@pytest.mark.parametrize("model", SONNET_55_MODELS)
def test_sonnet_5_entry_does_not_match_sonnet_55(model):
    """The claude-sonnet-5 entry must not swallow Sonnet 5.5 (between_tools)."""
    body = json.dumps({"model": model, "thinking": {"type": "adaptive"},
                       "output_config": {"effort": "low"}}).encode()
    out = json.loads(anthropic_bridge.transform_request_body(body))
    assert out["thinking"] == {"type": "between_tools"}
    assert "output_config" not in out


def test_adaptive_models_configurable():
    body = json.dumps({"model": "claude-opus-6", "thinking": {"type": "adaptive"}}).encode()
    out = anthropic_bridge.transform_request_body(body, adaptive_models=("claude-opus-6",))
    assert out == body


def test_thinking_enabled_without_budget_is_floored():
    """LOW1: bare {type:"enabled"} (no budget_tokens) would 400 on Copilot;
    normalize it up to the configured budget (>= 1024)."""
    body = json.dumps({"thinking": {"type": "enabled"}}).encode()
    out = anthropic_bridge.transform_request_body(body, thinking_budget=4096)
    assert json.loads(out)["thinking"] == {"type": "enabled", "budget_tokens": 4096}


def test_thinking_enabled_with_too_small_budget_is_raised():
    """LOW1: {type:"enabled", budget_tokens:<1024} is raised to a valid value."""
    body = json.dumps({"thinking": {"type": "enabled", "budget_tokens": 500}}).encode()
    out = anthropic_bridge.transform_request_body(body, thinking_budget=8192)
    assert json.loads(out)["thinking"] == {"type": "enabled", "budget_tokens": 8192}


def test_thinking_enabled_with_valid_budget_unchanged():
    """LOW1: {type:"enabled", budget_tokens:>=1024} is left as-is."""
    body = json.dumps({"thinking": {"type": "enabled", "budget_tokens": 2048}}).encode()
    out = anthropic_bridge.transform_request_body(body)
    assert json.loads(out)["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert out == body  # no needless reserialize when already valid


def test_thinking_enabled_configured_budget_below_floor_uses_1024():
    """LOW1: even a misconfigured default below 1024 is floored to 1024, never
    forwarded as an invalid value."""
    body = json.dumps({"thinking": {"type": "enabled"}}).encode()
    out = anthropic_bridge.transform_request_body(body, thinking_budget=100)
    assert json.loads(out)["thinking"] == {"type": "enabled", "budget_tokens": 1024}


def test_thinking_enabled_non_int_budget_crash_safe():
    """LOW1: a non-int budget_tokens (string/bool/null) is treated as invalid
    and floored, never crashing."""
    for bad in ("2048", True, None, 3.5, {"n": 1}):
        body = json.dumps({"thinking": {"type": "enabled", "budget_tokens": bad}}).encode()
        out = anthropic_bridge.transform_request_body(body, thinking_budget=4096)
        assert json.loads(out)["thinking"] == {"type": "enabled", "budget_tokens": 4096}


def test_thinking_non_dict_is_left_alone():
    """LOW1: a non-dict thinking value is not a dict path -> untouched, no crash."""
    for th in ("enabled", 5, ["enabled"], None):
        body = json.dumps({"thinking": th, "messages": []}).encode()
        out = anthropic_bridge.transform_request_body(body)
        assert json.loads(out)["thinking"] == th


# --------------------------------------------------------------------------
# Body invariants
# --------------------------------------------------------------------------
def test_clean_body_returned_unchanged_identically():
    body = json.dumps({"model": "claude-sonnet-5", "messages": [{"role": "user"}]}).encode()
    out = anthropic_bridge.transform_request_body(body)
    assert out == body  # unchanged object => same bytes, no needless reserialize


def test_non_json_body_untouched():
    body = b"not json at all"
    assert anthropic_bridge.transform_request_body(body) == body


def test_empty_body_untouched():
    assert anthropic_bridge.transform_request_body(b"") == b""


def test_all_transforms_combined():
    body = json.dumps({
        "model": "claude-haiku-4.5",
        "output_config": {"reasoning_effort": "high"},
        "thinking": {"type": "adaptive"},
        "messages": [{"role": "user", "content": "hi"}],
    }).encode()
    out = anthropic_bridge.transform_request_body(body)
    obj = json.loads(out)
    assert "output_config" not in obj
    assert obj["thinking"] == {"type": "disabled"}
    assert obj["model"] == "claude-haiku-4.5"


# --------------------------------------------------------------------------
# Content-length recompute: a mutated bridge body must change its byte length
# so build_upstream_headers(...) sets the correct content-length.
# --------------------------------------------------------------------------
def test_content_length_recompute_on_mutated_body():
    body = json.dumps({
        "output_config": {"reasoning_effort": "high"},
        "thinking": {"type": "adaptive"},
        "messages": [],
    }).encode()
    out = anthropic_bridge.transform_request_body(body)
    assert len(out) != len(body)
    fwd = proxy.build_upstream_headers(
        {"authorization": "Bearer fake"}, BILLABLE_HOST, "Bearer fake",
        len(out), "github_pat_REAL")
    assert fwd["content-length"] == str(len(out))


# --------------------------------------------------------------------------
# Non-bridge path is untouched (proxy-level scoping guard)
# --------------------------------------------------------------------------
def test_chat_completions_is_not_a_bridge_request():
    # The Copilot CLI's own OpenAI path must never be normalized.
    assert anthropic_bridge.is_bridge_request(BILLABLE_HOST, "POST", "/chat/completions") is False
