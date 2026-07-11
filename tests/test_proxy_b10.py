"""B10 (P3): _read_head 64KB cap, duplicate Set-Cookie preservation,
CONNECT-leftover note."""
import asyncio
import logging

from multidict import CIMultiDict

import proxy as proxy_mod


# --------------------------------------------------------------------------- #
# _read_head cap
# --------------------------------------------------------------------------- #
async def test_read_head_caps_oversized_head(caplog):
    r = asyncio.StreamReader()
    # >64KB with no header terminator.
    r.feed_data(b"GET / HTTP/1.1\r\nX-Pad: " + b"a" * (70 * 1024))
    r.feed_eof()
    with caplog.at_level(logging.WARNING, logger="proxy"):
        assert await proxy_mod._read_head(r) is None
    assert "exceeded" in caplog.text


async def test_read_head_normal_head_ok():
    r = asyncio.StreamReader()
    r.feed_data(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    r.feed_eof()
    raw = await proxy_mod._read_head(r)
    assert raw is not None and b"\r\n\r\n" in raw


# --------------------------------------------------------------------------- #
# duplicate Set-Cookie preserved
# --------------------------------------------------------------------------- #
def test_headers_block_preserves_duplicate_set_cookie():
    h = CIMultiDict()
    h.add("Set-Cookie", "a=1")
    h.add("Set-Cookie", "b=2")
    h.add("Content-Type", "text/plain")
    block = proxy_mod._headers_block(h, {"connection"}, {"Connection": "keep-alive"})
    assert block.count("Set-Cookie:") == 2
    assert "a=1" in block and "b=2" in block


class _RecordingWriter:
    def __init__(self):
        self.buf = bytearray()

    def write(self, data):
        self.buf.extend(data)

    async def drain(self):
        pass


class _EmptyContent:
    async def iter_chunked(self, n):
        return
        yield  # pragma: no cover  (makes this an async generator)


class _FakeResp:
    def __init__(self, status, headers):
        self.status = status
        self.reason = "OK"
        self.headers = headers
        self.content = _EmptyContent()

    async def read(self):
        return b""


async def test_relay_response_emits_both_set_cookies():
    h = CIMultiDict()
    h.add("Set-Cookie", "s1=one")
    h.add("Set-Cookie", "s2=two")
    h.add("Content-Type", "text/event-stream")  # no Content-Length -> chunked path
    resp = _FakeResp(200, h)
    w = _RecordingWriter()
    await proxy_mod._relay_response(w, resp, "h", "/x")
    text = bytes(w.buf).decode("latin-1")
    assert text.count("Set-Cookie:") == 2
    assert "s1=one" in text and "s2=two" in text
