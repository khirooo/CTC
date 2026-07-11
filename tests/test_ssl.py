import ssl
import proxy


def test_default_context_verifies():
    ctx = proxy.build_upstream_ssl_context(False, None)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_insecure_context_disables_verification():
    ctx = proxy.build_upstream_ssl_context(True, None)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_parse_insecure_requires_both_flags():
    # Neither flag: verification stays on.
    assert proxy._parse_insecure({}) is False
    # Bare UPSTREAM_INSECURE without confirm: refused (stays on).
    assert proxy._parse_insecure({"UPSTREAM_INSECURE": "1"}) is False
    # Confirm without insecure: no effect.
    assert proxy._parse_insecure({"UPSTREAM_INSECURE_CONFIRM": "1"}) is False
    # Both truthy: insecure enabled.
    assert proxy._parse_insecure(
        {"UPSTREAM_INSECURE": "1", "UPSTREAM_INSECURE_CONFIRM": "1"}) is True
    assert proxy._parse_insecure(
        {"UPSTREAM_INSECURE": "true", "UPSTREAM_INSECURE_CONFIRM": "yes"}) is True
    # Falsey insecure with confirm: off.
    assert proxy._parse_insecure(
        {"UPSTREAM_INSECURE": "0", "UPSTREAM_INSECURE_CONFIRM": "1"}) is False


def test_upstream_ssl_context_is_cached_singleton():
    # The cached context must be the SAME object across calls: aiohttp keys its
    # connection pool by SSLContext identity, so a fresh context per call would
    # silently disable connection reuse (P1-4).
    proxy._upstream_ssl = None
    try:
        ctx1 = proxy.upstream_ssl_context()
        ctx2 = proxy.upstream_ssl_context()
        assert ctx1 is ctx2
    finally:
        proxy._upstream_ssl = None
