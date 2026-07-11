"""B3 (P1-1 + P2 mid-stream): debit on client disconnect; abort instead of
writing a 502 into an open chunked body."""
import asyncio
import types

import aiohttp
import pytest

import proxy as proxy_mod
from conftest import TEST_HOST
from ctc.auth.identity import ConsumerIdentity


# --------------------------------------------------------------------------- #
# Fakes for unit tests
# --------------------------------------------------------------------------- #
class _FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_chunked(self, n):
        for c in self._chunks:
            yield c


class _FakeResp:
    def __init__(self, status, headers, chunks=None, body=b""):
        self.status = status
        self.reason = "OK"
        self.headers = headers
        self.content = _FakeContent(chunks or [])
        self._body = body

    async def read(self):
        return self._body


class _FakeWriter:
    """Records writes; raises ConnectionResetError on the Nth drain to model a
    client that hung up mid-stream. `transport` is self so abort() is observable."""
    def __init__(self, fail_on_drain=None):
        self.writes = []
        self.drains = 0
        self.fail_on_drain = fail_on_drain
        self.aborted = False
        self.transport = self

    def write(self, data):
        self.writes.append(bytes(data))

    async def drain(self):
        self.drains += 1
        if self.fail_on_drain is not None and self.drains >= self.fail_on_drain:
            raise ConnectionResetError("client gone")

    def abort(self):
        self.aborted = True


# --------------------------------------------------------------------------- #
# RelayState capture in _relay_response
# --------------------------------------------------------------------------- #
async def test_relay_state_captured_on_disconnect_midstream():
    headers = {"Content-Type": "text/event-stream"}  # no CL -> chunked path
    usage = b'data: {"copilot_usage":{"total_nano_aiu":42}}\n\n'
    resp = _FakeResp(200, headers, chunks=[usage, b"more", b"tail"])
    w = _FakeWriter(fail_on_drain=2)  # head drain (#1) ok, first chunk drain (#2) fails
    state = proxy_mod.RelayState()
    with pytest.raises(ConnectionResetError):
        await proxy_mod._relay_response(w, resp, "h", "/v1/messages", capture_full=True, state=state)
    assert state.head_sent is True
    assert state.status == 200
    assert bytes(state.body) == usage  # partial bytes captured for the debit


async def test_relay_state_head_not_sent_before_first_write():
    # A response we never got to write (drain fails on the very first head write)
    headers = {"Content-Type": "text/event-stream"}
    resp = _FakeResp(200, headers, chunks=[b"x"])
    w = _FakeWriter(fail_on_drain=1)  # head drain fails
    state = proxy_mod.RelayState()
    with pytest.raises(ConnectionResetError):
        await proxy_mod._relay_response(w, resp, "h", "/v1/messages", capture_full=True, state=state)
    # head_sent is set right when we write the head, before draining it
    assert state.head_sent is True


# --------------------------------------------------------------------------- #
# _fail_client
# --------------------------------------------------------------------------- #
def test_fail_client_aborts_when_head_sent():
    w = _FakeWriter()
    state = proxy_mod.RelayState()
    state.head_sent = True
    proxy_mod._fail_client(w, state, b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
    assert w.aborted is True
    assert w.writes == []  # no status line injected into the open body


def test_fail_client_writes_status_when_head_not_sent():
    w = _FakeWriter()
    state = proxy_mod.RelayState()
    proxy_mod._fail_client(w, state, b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
    assert w.aborted is False
    assert w.writes and w.writes[0].startswith(b"HTTP/1.1 502")


# --------------------------------------------------------------------------- #
# _reconcile_partial_relay
# --------------------------------------------------------------------------- #
class _RecordingAttr:
    def __init__(self):
        self.debits = []

    def debit(self, cid, consumer, source, cost, ts):
        self.debits.append(cost)


def _state_with_usage(nano):
    st = proxy_mod.RelayState()
    st.status = 200
    st.content_type = "text/event-stream"
    st.body = bytearray(
        ('data: {"copilot_usage":{"total_nano_aiu":%d},"type":"message_delta"}\n\n' % nano).encode())
    return st


def test_reconcile_partial_relay_debits_once(monkeypatch):
    attr = _RecordingAttr()
    monkeypatch.setattr(proxy_mod, "ATTRIBUTION", attr)
    st = _state_with_usage(8262952500)
    cycle = types.SimpleNamespace(id="c1")
    proxy_mod._reconcile_partial_relay(True, False, st, cycle, object(), object(), "/v1/messages")
    assert attr.debits == [8262952500]


def test_reconcile_partial_relay_skips_when_already_debited(monkeypatch):
    attr = _RecordingAttr()
    monkeypatch.setattr(proxy_mod, "ATTRIBUTION", attr)
    st = _state_with_usage(100)
    cycle = types.SimpleNamespace(id="c1")
    proxy_mod._reconcile_partial_relay(True, True, st, cycle, object(), object(), "/v1/messages")
    assert attr.debits == []


def test_reconcile_partial_relay_skips_non_200(monkeypatch):
    attr = _RecordingAttr()
    monkeypatch.setattr(proxy_mod, "ATTRIBUTION", attr)
    st = _state_with_usage(100)
    st.status = 502
    cycle = types.SimpleNamespace(id="c1")
    proxy_mod._reconcile_partial_relay(True, False, st, cycle, object(), object(), "/v1/messages")
    assert attr.debits == []


def test_reconcile_partial_relay_skips_non_billable(monkeypatch):
    attr = _RecordingAttr()
    monkeypatch.setattr(proxy_mod, "ATTRIBUTION", attr)
    st = _state_with_usage(100)
    cycle = types.SimpleNamespace(id="c1")
    proxy_mod._reconcile_partial_relay(False, False, st, cycle, object(), object(), "/v1/messages")
    assert attr.debits == []


# --------------------------------------------------------------------------- #
# Integration: recording ATTRIBUTION stub + billable SSE route
# --------------------------------------------------------------------------- #
class _StubSource:
    pat = "github_pat_STUB0000000000000000000000000000000"
    giver_id = "g1"
    grant_id = None


class _StubEngine:
    def ensure_active_cycle(self, now):
        return types.SimpleNamespace(id="c1")

    def active_grants(self, cid, uid):
        return []


class _StubAttribution:
    def __init__(self):
        self.engine = _StubEngine()
        self.debits = []

    def resolve_consumer(self, token):
        return ConsumerIdentity("consumer1", is_giver=True)

    def select_source(self, cid, consumer, health=None, exclude=frozenset()):
        return _StubSource()

    def pinned_source(self, key, *, cycle_id=None, health=None, now=None):
        return None

    def pin_source(self, *a, **k):
        pass

    def debit(self, cid, consumer, source, cost, ts):
        self.debits.append(cost)

    def any_giver_pat(self):
        return _StubSource.pat


@pytest.fixture
def billable_proxy(running_proxy, monkeypatch):
    """running_proxy with TEST_HOST treated as the billable copilot-api host and
    a recording ATTRIBUTION stub installed."""
    attr = _StubAttribution()
    monkeypatch.setattr(proxy_mod, "ATTRIBUTION", attr)
    monkeypatch.setattr(proxy_mod, "LIVE_QUOTA", None)
    monkeypatch.setattr(proxy_mod, "_COPILOT_API_HOST", TEST_HOST)
    monkeypatch.setattr(proxy_mod, "_BILLABLE_PATHS",
                        proxy_mod._BILLABLE_PATHS | {"/billable-sse", "/upstream-dies"})
    monkeypatch.setattr(proxy_mod, "MITM_HOSTS", {TEST_HOST})
    monkeypatch.setattr(proxy_mod, "SWAP_HOSTS", {TEST_HOST})
    return {"attr": attr, **running_proxy}


async def test_client_disconnect_midstream_debits_exactly_once(billable_proxy, client_ssl):
    attr = billable_proxy["attr"]
    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with aiohttp.ClientSession(connector=connector) as s:
        r = await s.post(f"https://{TEST_HOST}/billable-sse", data=b"{}",
                         proxy=f"http://127.0.0.1:{billable_proxy['port']}",
                         headers={"Authorization": "token x"})
        conn = r.connection
        await r.content.readline()   # read part of the stream
        # Hard client disconnect (RST) so the proxy's next drain fails.
        if conn is not None and conn.transport is not None:
            conn.transport.abort()
        r.close()
    # Give the proxy loop time to observe the reset and run the partial debit.
    for _ in range(50):
        await asyncio.sleep(0.05)
        if attr.debits:
            break
    assert len(attr.debits) == 1
    # The charge came from the early copilot_usage event captured before the drop.
    assert attr.debits[0] == 8262952500


async def test_upstream_death_midstream_no_502_in_body(billable_proxy, client_ssl):
    connector = aiohttp.TCPConnector(ssl=client_ssl)
    received = bytearray()
    async with aiohttp.ClientSession(connector=connector) as s:
        try:
            async with s.post(f"https://{TEST_HOST}/upstream-dies", data=b"{}",
                              proxy=f"http://127.0.0.1:{billable_proxy['port']}",
                              headers={"Authorization": "token x"}) as r:
                assert r.status == 200
                try:
                    async for chunk in r.content.iter_any():
                        received.extend(chunk)
                except aiohttp.ClientError:
                    pass  # connection reset mid-stream, as expected
        except aiohttp.ClientError:
            pass
    # The client got the streamed head + partial body then a reset — never a
    # well-formed 502 status line injected into the chunked body.
    assert b"502" not in received
