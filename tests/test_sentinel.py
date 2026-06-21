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
