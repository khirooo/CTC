"""B9: streamed capture/billing buffer is bounded to a trailing window that
still contains the final SSE charge event."""
import proxy as proxy_mod


class _FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_chunked(self, n):
        for c in self._chunks:
            yield c


class _FakeResp:
    def __init__(self, status, headers, chunks):
        self.status = status
        self.reason = "OK"
        self.headers = headers
        self.content = _FakeContent(chunks)


class _NullWriter:
    def write(self, data):
        pass

    async def drain(self):
        pass


async def test_oversized_stream_keeps_trailing_usage():
    filler = b"data: filler\n\n" * 40000            # ~560 KB, well over the cap
    usage = b'data: {"copilot_usage":{"total_nano_aiu":777},"type":"message_delta"}\n\n'
    resp = _FakeResp(200, {"Content-Type": "text/event-stream"}, chunks=[filler, usage])
    state = proxy_mod.RelayState()
    body = await proxy_mod._relay_response(
        _NullWriter(), resp, "h", "/v1/messages", capture_full=True, state=state)
    # Buffer bounded...
    assert len(body) <= proxy_mod.CAPTURE_TAIL_CAP
    assert len(bytes(state.body)) <= proxy_mod.CAPTURE_TAIL_CAP
    # ...yet the trailing charge event survived, so billing still extracts it.
    assert proxy_mod.extract_total_nano_aiu(body, "text/event-stream") == 777
