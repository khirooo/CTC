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
