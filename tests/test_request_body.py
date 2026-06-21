import asyncio
import proxy


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
