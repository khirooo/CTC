import asyncio
import proxy
import pytest


async def _reader_with(data: bytes):
    r = asyncio.StreamReader()
    r.feed_data(data)
    r.feed_eof()
    return r


async def test_chunked_body_dechunked():
    r = await _reader_with(b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n")
    body = await proxy.assemble_request_body(r, {"transfer-encoding": "chunked"}, b"")
    assert body == b"hello world"


async def test_content_length_body_with_leftover():
    r = await _reader_with(b"llo")
    body = await proxy.assemble_request_body(r, {"content-length": "5"}, b"he")
    assert body == b"hello"


async def test_no_body():
    r = await _reader_with(b"")
    body = await proxy.assemble_request_body(r, {}, b"")
    assert body == b""


async def test_chunked_body_with_leftover():
    r = await _reader_with(b"hello\r\n0\r\n\r\n")
    body = await proxy.assemble_request_body(r, {"transfer-encoding": "chunked"}, b"5\r\n")
    assert body == b"hello"


# --- B5 hardening ---------------------------------------------------------- #
async def test_chunked_consumes_trailers():
    # 0-chunk followed by a trailer header, then the terminating blank line.
    r = await _reader_with(b"5\r\nhello\r\n0\r\nX-Trailer: v\r\n\r\n")
    body = await proxy.assemble_request_body(r, {"transfer-encoding": "chunked"}, b"")
    assert body == b"hello"


async def test_chunked_eof_midchunk_raises():
    r = await _reader_with(b"5\r\nhel")  # declares 5 bytes, only 3 arrive then EOF
    with pytest.raises(proxy.RequestBodyError):
        await proxy.assemble_request_body(r, {"transfer-encoding": "chunked"}, b"")


async def test_chunked_eof_before_size_raises():
    r = await _reader_with(b"")  # chunked but nothing at all
    with pytest.raises(proxy.RequestBodyError):
        await proxy.assemble_request_body(r, {"transfer-encoding": "chunked"}, b"")


async def test_chunked_bad_size_raises():
    r = await _reader_with(b"zz\r\nhello\r\n0\r\n\r\n")
    with pytest.raises(proxy.RequestBodyError):
        await proxy.assemble_request_body(r, {"transfer-encoding": "chunked"}, b"")


async def test_content_length_short_read_raises():
    r = await _reader_with(b"hel")  # only 3 of 5 bytes then EOF
    with pytest.raises(proxy.RequestBodyError):
        await proxy.assemble_request_body(r, {"content-length": "5"}, b"")


async def test_content_length_truncates_excess_leftover():
    # 10 bytes buffered but Content-Length says 5 -> forward exactly 5, drop rest
    r = await _reader_with(b"")
    body = await proxy.assemble_request_body(r, {"content-length": "5"}, b"HELLOWORLD")
    assert body == b"HELLO"


async def test_bad_content_length_raises():
    r = await _reader_with(b"abc")
    with pytest.raises(proxy.RequestBodyError):
        await proxy.assemble_request_body(r, {"content-length": "notanumber"}, b"")


async def test_malformed_chunked_body_returns_400(running_proxy):
    reader, writer = await asyncio.open_connection("127.0.0.1", running_proxy["port"])
    # Plain (non-CONNECT) HTTP request with a chunked body that EOFs mid-chunk.
    writer.write(b"POST /x HTTP/1.1\r\nHost: ghe.test\r\n"
                 b"Transfer-Encoding: chunked\r\n\r\n5\r\nhel")
    await writer.drain()
    writer.write_eof()
    data = await reader.read(4096)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    assert b"400 Bad Request" in data
