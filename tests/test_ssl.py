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
