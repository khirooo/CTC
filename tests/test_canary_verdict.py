import json
import os

from ctc import canary

FX = os.path.join(os.path.dirname(__file__), "fixtures", "canary")


def _load(name):
    return canary.load_exchanges(os.path.join(FX, name))


def test_pass_fixture_passes_with_nonzero_debit():
    v = canary.evaluate(_load("pass.ndjson"), debited_nano_aiu=8262952500)
    assert v.verdict == "pass"
    assert v.failures == []
    assert v.extracted_nano_aiu == 8262952500


def test_missing_metering_field_fails():
    v = canary.evaluate(_load("no_field.ndjson"), debited_nano_aiu=0)
    assert v.verdict == "fail"
    assert any(f["assertion"] == "metering_field_present" for f in v.failures)


def test_zero_debit_on_priced_call_fails():
    # Body has a priced field but the debit recorded 0 -> extraction/debit broke.
    v = canary.evaluate(_load("pass.ndjson"), debited_nano_aiu=0)
    assert v.verdict == "fail"
    assert any(f["assertion"] == "nonzero_aiu_debited" for f in v.failures)


def test_unexpected_host_fails():
    v = canary.evaluate(_load("bypassed_host.ndjson"), debited_nano_aiu=5)
    assert v.verdict == "fail"
    assert any(f["assertion"] == "hosts_within_contract" for f in v.failures)


def test_billable_rejection_fails():
    v = canary.evaluate(_load("rejected.ndjson"), debited_nano_aiu=None)
    assert v.verdict == "fail"
    assert any(f["assertion"] == "billable_succeeded" for f in v.failures)


def test_null_total_nano_aiu_is_field_absent():
    # Regression: a body with total_nano_aiu:null used to pass the substring
    # check ("copilot_usage" in body AND "total_nano_aiu" in body) even though
    # the field is semantically absent (non-numeric). evaluate must report a
    # metering_field_present failure for this exchange.
    exchanges = [
        {
            "method": "POST",
            "path": "/chat/completions",
            "host": "copilot-api.example.ghe.com",
            "status": 200,
            "response_content_type": "application/json",
            "body": '{"error":"copilot_usage not available","copilot_usage":{"total_nano_aiu":null}}',
        }
    ]
    v = canary.evaluate(exchanges, debited_nano_aiu=0)
    assert any(f["assertion"] == "metering_field_present" for f in v.failures), (
        "expected metering_field_present failure for null total_nano_aiu, got: " + str(v.failures)
    )


def test_missing_status_key_does_not_raise():
    # Regression: sorted({ex.get("status") for ex in billable}) raises TypeError
    # when None mixes with int in the set — e.g. one billable exchange has a
    # numeric status and another has no "status" key at all. evaluate must
    # return a Verdict without raising.
    exchanges = [
        {
            "method": "POST",
            "path": "/chat/completions",
            "host": "copilot-api.example.ghe.com",
            "status": 403,
            "response_content_type": "application/json",
            "body": "{}",
        },
        {
            "method": "POST",
            "path": "/chat/completions",
            "host": "copilot-api.example.ghe.com",
            # No "status" key — simulates a malformed/truncated record.
            "response_content_type": "application/json",
            "body": "{}",
        },
    ]
    # Should not raise; we don't care about pass/fail, just no exception.
    v = canary.evaluate(exchanges, debited_nano_aiu=None)
    assert isinstance(v, canary.Verdict)


def test_capture_record_schema_matches_canary_reader(tmp_path):
    # Drift guard: the canary must read exactly what capture.record_exchange
    # writes. This once diverged (writer used host/body, reader read
    # upstream_host/response_body) so the contract canary failed on every real
    # run while its hand-authored fixtures still passed. Feed a real captured
    # record through evaluate() to keep the two in lockstep.
    from ctc.metering.capture import record_exchange
    from ctc import contract

    record_exchange(
        str(tmp_path),
        method=contract.BILLABLE_METHOD,
        path=next(iter(contract.BILLABLE_PATHS)),
        upstream_host=contract.BILLABLE_HOST,
        status=200,
        request_headers={},
        response_headers={},
        response_body=b'{"copilot_usage":{"total_nano_aiu":8262952500}}',
        response_content_type="application/json",
    )
    exchanges = canary.load_exchanges(str(tmp_path / "exchanges.ndjson"))
    v = canary.evaluate(exchanges, debited_nano_aiu=8262952500)
    assert v.verdict == "pass", v.failures
    assert v.extracted_nano_aiu == 8262952500


def test_write_status_roundtrip(tmp_path):
    v = canary.evaluate(_load("pass.ndjson"), debited_nano_aiu=8262952500)
    p = tmp_path / "canary-status.json"
    canary.write_status(str(p), v, ran_at="2026-06-20T00:00:00Z", copilot_version="1.2.3")
    data = json.loads(p.read_text())
    assert data["verdict"] == "pass"
    assert data["copilot_version"] == "1.2.3"
    assert data["ran_at"] == "2026-06-20T00:00:00Z"
    assert data["extracted_nano_aiu"] == 8262952500
    assert data["failures"] == []
