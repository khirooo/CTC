"""A billable 401 from the Copilot API host means the swapped PAT was refused.

Before this failover existed the proxy retried the same rejected PAT for as long
as the client kept asking: `is_invalid_auto_mode_selector_401` was the only 401
that re-selected a giver, so a PAT that was revoked, expired, or missing the
fine-grained "Copilot Requests" permission hard-stuck every consumer routed to it
until the next health sweep (up to CTC_PAT_HEALTH_INTERVAL_S away).
"""
import types

import aiohttp
import proxy as proxy_mod
import pytest

from ctc.auth.identity import ConsumerIdentity
from tests.conftest import TEST_HOST


BAD_PAT = "github_pat_REJECTED00000000000000000000000000"
GOOD_PAT = "github_pat_HEALTHY000000000000000000000000000"


# --------------------------------------------------------------------------- #
# is_pat_rejected_401
# --------------------------------------------------------------------------- #
def test_missing_permission_401_is_a_pat_rejection():
    body = (b'checking third-party user token: unauthorized: '
            b'Personal Access Token does not have "Copilot Requests" permission')
    assert proxy_mod.is_pat_rejected_401(401, body) is True


def test_expired_token_401_is_a_pat_rejection():
    assert proxy_mod.is_pat_rejected_401(
        401, b"unauthorized: AuthenticateToken authentication failed") is True


def test_auto_mode_selector_401_is_not_a_pat_rejection():
    # That 401 has its own, richer recovery (re-bootstrap the session token);
    # claiming it here would bypass the heal and just burn a giver.
    from ctc import contract
    body = contract.INVALID_AUTO_MODE_SELECTOR_BODY.encode()
    assert proxy_mod.is_pat_rejected_401(401, body) is False


@pytest.mark.parametrize("status", [200, 402, 403, 500])
def test_non_401_is_never_a_pat_rejection(status):
    assert proxy_mod.is_pat_rejected_401(status, b"whatever") is False


# --------------------------------------------------------------------------- #
# End-to-end failover
# --------------------------------------------------------------------------- #
class _Source:
    def __init__(self, giver_id, pat):
        self.giver_id = giver_id
        self.pat = pat
        self.grant_id = None


class _Engine:
    def ensure_active_cycle(self, now):
        return types.SimpleNamespace(id="c1")

    def active_grants(self, cid, uid):
        return []

    def sync_quota_ceiling(self, *a, **k):
        pass

    def reconcile_giver(self, *a, **k):
        pass


class _Attribution:
    """Hands out the rejected giver first, then the healthy one once excluded."""

    def __init__(self):
        self.engine = _Engine()
        self.selects = []
        self.debits = []

    def resolve_consumer(self, token):
        return ConsumerIdentity("consumer1", is_giver=True)

    def select_source(self, cid, consumer, health=None, exclude=frozenset()):
        self.selects.append(frozenset(exclude))
        if "g_bad" in exclude:
            return _Source("g_good", GOOD_PAT)
        return _Source("g_bad", BAD_PAT)

    def pinned_source(self, key, *, cycle_id=None, health=None, now=None):
        return None

    def pin_source(self, *a, **k):
        pass

    def debit(self, cid, consumer, source, cost, ts):
        self.debits.append((source.giver_id, cost))

    def any_giver_pat(self):
        return GOOD_PAT


class _Cache:
    """Live-quota cache stub. A non-None remaining is what gives `health` an entry,
    which is what raises max_attempts above 1 and so permits any failover at all."""

    async def get(self, gid):
        return {"entitlement": 4000, "remaining": 4000}

    def set_exhausted(self, gid):
        pass


@pytest.fixture
def rejecting_proxy(running_proxy, monkeypatch):
    attr = _Attribution()
    monkeypatch.setattr(proxy_mod, "ATTRIBUTION", attr)
    monkeypatch.setattr(proxy_mod, "LIVE_QUOTA", _Cache())
    monkeypatch.setattr(proxy_mod, "_COPILOT_API_HOST", TEST_HOST)
    monkeypatch.setattr(proxy_mod, "_BILLABLE_PATHS",
                        proxy_mod._BILLABLE_PATHS | {"/pat-rejected"})
    monkeypatch.setattr(proxy_mod, "MITM_HOSTS", {TEST_HOST})
    monkeypatch.setattr(proxy_mod, "SWAP_HOSTS", {TEST_HOST})
    return {"attr": attr, **running_proxy}


async def _post(port, client_ssl, path="/pat-rejected"):
    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with aiohttp.ClientSession(connector=connector) as s:
        async with s.post(f"https://{TEST_HOST}{path}", data=b"{}",
                          proxy=f"http://127.0.0.1:{port}",
                          headers={"Authorization": "token ctc-fake"}) as r:
            return r.status, await r.read()


@pytest.mark.asyncio
async def test_rejected_pat_fails_over_to_the_next_giver(rejecting_proxy, client_ssl,
                                                         mock_upstream):
    status, _ = await _post(rejecting_proxy["port"], client_ssl)

    # The client sees the healthy giver's 200, never the rejected giver's 401.
    assert status == 200
    # The rejected giver was excluded and a second selection ran.
    attr = rejecting_proxy["attr"]
    assert attr.selects == [frozenset(), frozenset({"g_bad"})]
    # The healthy giver carried the request, so it is the one debited.
    assert [g for g, _ in attr.debits] == ["g_good"]
    assert mock_upstream["received"]["auth"] == f"Bearer {GOOD_PAT}"


@pytest.mark.asyncio
async def test_401_is_relayed_when_no_other_giver_is_left(running_proxy, client_ssl,
                                                          monkeypatch):
    """Failing over is not the same as hiding the failure: with nothing left to
    try, the upstream 401 must reach the client rather than loop."""
    attr = _Attribution()
    monkeypatch.setattr(attr, "select_source",
                        lambda cid, c, health=None, exclude=frozenset():
                        None if exclude else _Source("g_bad", BAD_PAT))
    monkeypatch.setattr(proxy_mod, "ATTRIBUTION", attr)
    monkeypatch.setattr(proxy_mod, "LIVE_QUOTA", _Cache())
    monkeypatch.setattr(proxy_mod, "_COPILOT_API_HOST", TEST_HOST)
    monkeypatch.setattr(proxy_mod, "_BILLABLE_PATHS",
                        proxy_mod._BILLABLE_PATHS | {"/pat-rejected"})
    monkeypatch.setattr(proxy_mod, "MITM_HOSTS", {TEST_HOST})
    monkeypatch.setattr(proxy_mod, "SWAP_HOSTS", {TEST_HOST})

    status, body = await _post(running_proxy["port"], client_ssl)

    assert status == 401
    assert b"Copilot Requests" in body
    assert attr.debits == []
