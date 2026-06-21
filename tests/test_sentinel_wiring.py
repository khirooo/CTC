import logging

import proxy
from ctc.sentinel import Finding


def test_emit_finding_logs_structured_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="proxy"):
        proxy._emit_finding(Finding("metering_field_missing", "billable 200 with no copilot_usage.total_nano_aiu field (path=/chat/completions)"))
    msgs = [r.getMessage() for r in caplog.records]
    assert any("event=ctc.drift" in m and "kind=metering_field_missing" in m for m in msgs)


def test_emit_finding_noop_on_none(caplog):
    with caplog.at_level(logging.WARNING, logger="proxy"):
        proxy._emit_finding(None)
    assert not caplog.records


# --- Fix 1: sentinel emit guard — exceptions must never propagate ---
def test_sentinel_emit_guard_swallows_detector_exception(monkeypatch, caplog):
    """proxy._safe_sentinel_emit must catch any exception from the detector
    and log it, never re-raise — so the 502 handler is never reached after
    the response is already sent."""
    import ctc.sentinel as _s

    def _raising_detector(*_args, **_kwargs):
        raise RuntimeError("simulated sentinel crash")

    monkeypatch.setattr(_s, "check_billable_response", _raising_detector)

    # _safe_sentinel_emit(fn, *args) must not raise even when fn raises.
    with caplog.at_level(logging.ERROR, logger="proxy"):
        # Should not raise:
        proxy._safe_sentinel_emit(_s.check_billable_response, 200, b"{}", "application/json", "/chat/completions")

    # Confirm the error was logged, not silently swallowed without trace.
    assert any("sentinel" in r.getMessage().lower() or "simulated sentinel crash" in r.getMessage()
               for r in caplog.records)


# --- Fix I-1: bypassed-host sentinel path uses _safe_sentinel_emit ---
def test_bypassed_host_emit_guard_swallows_exception(monkeypatch, caplog):
    """_safe_sentinel_emit called for check_bypassed_host must catch any
    exception from the detector and log it — a broken sentinel must never
    corrupt the blind-tunnel path or propagate to the caller."""
    import ctc.sentinel as _s

    def _raising_bypassed(*_args, **_kwargs):
        raise RuntimeError("simulated bypassed-host sentinel crash")

    monkeypatch.setattr(_s, "check_bypassed_host", _raising_bypassed)

    with caplog.at_level(logging.ERROR, logger="proxy"):
        # Must not raise, even though the underlying detector raises.
        proxy._safe_sentinel_emit(_s.check_bypassed_host, "some.external.host")

    # The error must be logged, not silently dropped.
    assert any(
        "sentinel" in r.getMessage().lower()
        or "simulated bypassed-host sentinel crash" in r.getMessage()
        for r in caplog.records
    )
