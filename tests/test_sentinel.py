from ctc import sentinel

# Reuse real shapes (mirrors tests/test_extract.py fixtures).
JSON_FREE = (
    '{"choices":[{"message":{"content":"hi"}}],'
    '"usage":{"total_tokens":182},'
    '"copilot_usage":{"token_details":[],"total_nano_aiu":0}}'
)
JSON_PRICED = (
    '{"choices":[{"message":{"content":"hi"}}],'
    '"copilot_usage":{"total_nano_aiu":8262952500}}'
)
# Drift: a 200 completion body with NO copilot_usage field at all.
JSON_NO_FIELD = '{"choices":[{"message":{"content":"hi"}}],"usage":{"total_tokens":182}}'
SSE_PRICED = (
    "event: message_delta\n"
    'data: {"copilot_usage":{"total_nano_aiu":8262952500},"type":"message_delta"}\n\n'
    "data: [DONE]\n\n"
)
SSE_NO_FIELD = (
    "event: message_delta\n"
    'data: {"type":"message_delta","usage":{"output_tokens":326}}\n\n'
    "data: [DONE]\n\n"
)


# --- classify_usage: tri-state ---
def test_classify_present_zero_is_free_model():
    assert sentinel.classify_usage(JSON_FREE, "application/json", "/chat/completions") == "present_zero"


def test_classify_present_positive():
    assert sentinel.classify_usage(JSON_PRICED, "application/json", "/chat/completions") == "present_positive"


def test_classify_absent_is_drift():
    assert sentinel.classify_usage(JSON_NO_FIELD, "application/json", "/chat/completions") == "absent"


def test_classify_sse_present_positive():
    assert sentinel.classify_usage(SSE_PRICED, "text/event-stream", "/v1/messages") == "present_positive"


def test_classify_sse_absent_is_drift():
    assert sentinel.classify_usage(SSE_NO_FIELD, "text/event-stream", "/v1/messages") == "absent"


# --- check_billable_response: only 'absent' on a 200 is a finding ---
def test_free_model_200_no_finding():
    assert sentinel.check_billable_response(200, JSON_FREE, "application/json", "/chat/completions") is None


def test_priced_200_no_finding():
    assert sentinel.check_billable_response(200, JSON_PRICED, "application/json", "/chat/completions") is None


def test_missing_field_200_is_finding():
    f = sentinel.check_billable_response(200, JSON_NO_FIELD, "application/json", "/chat/completions")
    assert f is not None and f.kind == "metering_field_missing"


def test_non_200_is_not_a_metering_finding():
    # A 400/500 legitimately omits copilot_usage; not a metering-field finding.
    assert sentinel.check_billable_response(400, JSON_NO_FIELD, "application/json", "/chat/completions") is None


# --- check_bypassed_host ---
def test_github_host_bypassed_is_finding():
    f = sentinel.check_bypassed_host("copilot-api.example.ghe.com")
    assert f is not None and f.kind == "bypassed_github_host"


def test_unrelated_host_bypassed_no_finding():
    assert sentinel.check_bypassed_host("registry.npmjs.org") is None


# --- check_billable_rejection ---
def test_billable_401_is_finding():
    f = sentinel.check_billable_rejection(401, "/chat/completions")
    assert f is not None and f.kind == "billable_rejected"


def test_billable_200_no_rejection_finding():
    assert sentinel.check_billable_rejection(200, "/chat/completions") is None


# --- bridge self-heal 400 suppression (native Claude Code) ---
from ctc.contract import ANTHROPIC_BRIDGE_PATH

_SELF_HEAL_BODY = (
    b'{"type":"error","error":{"type":"invalid_request_error",'
    b'"message":"messages: Unexpected role \\"system\\". The Messages API accepts '
    b'a top-level `system` parameter, not \\"system\\" as an input message role."}}'
)


def test_bridge_self_heal_400_is_not_a_finding():
    """(a) native Claude Code's routine mid-conversation-system self-heal 400 on
    the bridge path must NOT emit the drift WARN."""
    assert sentinel.check_billable_rejection(400, ANTHROPIC_BRIDGE_PATH, _SELF_HEAL_BODY) is None
    # with query string on the path, still suppressed
    assert sentinel.check_billable_rejection(
        400, ANTHROPIC_BRIDGE_PATH + "?beta=true", _SELF_HEAL_BODY) is None
    # the mid-conversation-system marker alone also matches
    assert sentinel.check_billable_rejection(
        400, ANTHROPIC_BRIDGE_PATH,
        b'{"error":{"message":"mid-conversation-system not supported"}}') is None


def test_bridge_real_401_403_still_alarms():
    """(b) a genuine auth failure on the bridge path STILL emits the drift WARN,
    even with the same body present."""
    for status in (401, 403):
        f = sentinel.check_billable_rejection(status, ANTHROPIC_BRIDGE_PATH, _SELF_HEAL_BODY)
        assert f is not None and f.kind == "billable_rejected"


def test_bridge_non_self_heal_400_still_alarms():
    """(b) a 400 on the bridge path that is NOT the self-heal case still alarms —
    the suppression is wording-specific, not a blanket bridge-400 mute."""
    f = sentinel.check_billable_rejection(
        400, ANTHROPIC_BRIDGE_PATH,
        b'{"type":"error","error":{"message":"model claude-fable-5 not found"}}')
    assert f is not None and f.kind == "billable_rejected"
    # and a bridge 400 with no body at all still alarms (can't prove it benign)
    assert sentinel.check_billable_rejection(400, ANTHROPIC_BRIDGE_PATH) is not None


def test_copilot_cli_path_400_unchanged_even_with_self_heal_wording():
    """(c) the Copilot CLI path's drift behavior is unchanged: a 400 there always
    alarms, regardless of body — the suppression is scoped to the bridge path."""
    f = sentinel.check_billable_rejection(400, "/chat/completions", _SELF_HEAL_BODY)
    assert f is not None and f.kind == "billable_rejected"
    # /responses (also Copilot CLI, non-bridge) likewise unchanged
    f2 = sentinel.check_billable_rejection(400, "/responses", _SELF_HEAL_BODY)
    assert f2 is not None and f2.kind == "billable_rejected"


# --- classify_usage: type-guard for non-numeric total_nano_aiu (Fix 2) ---
def test_classify_null_nano_aiu_is_absent():
    """A present-but-null total_nano_aiu must be treated as absent (unusable/drifted),
    not as present_zero (which would mean a free model)."""
    body = '{"choices":[],"copilot_usage":{"total_nano_aiu":null}}'
    assert sentinel.classify_usage(body, "application/json", "/chat/completions") == "absent"


def test_classify_string_nano_aiu_is_absent():
    """A present-but-string total_nano_aiu must be treated as absent, not crash."""
    body = '{"choices":[],"copilot_usage":{"total_nano_aiu":"5"}}'
    assert sentinel.classify_usage(body, "application/json", "/chat/completions") == "absent"
