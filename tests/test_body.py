import gzip, zlib
import pytest
import proxy


def test_identity_json_is_pretty_printed():
    out = proxy.decode_body(b'{"a":1}', "", "application/json")
    assert '"a": 1' in out


def test_gzip_decodes():
    assert proxy.decode_body(gzip.compress(b"hello"), "gzip", "text/plain") == "hello"


def test_deflate_decodes():
    assert proxy.decode_body(zlib.compress(b"hello"), "deflate", "text/plain") == "hello"


def test_truncation_marked():
    out = proxy.decode_body(b"x" * 5000, "", "text/plain", limit=100)
    assert "truncated" in out


def test_partial_gzip_is_graceful():
    truncated = gzip.compress(b"hello world" * 100)[:20]
    out = proxy.decode_body(truncated, "gzip", "text/plain")
    assert "decode error" in out


def test_brotli_optional():
    brotli = pytest.importorskip("brotli")
    assert proxy.decode_body(brotli.compress(b"hello"), "br", "text/plain") == "hello"
