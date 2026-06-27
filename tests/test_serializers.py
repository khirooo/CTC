from ctc.api.serializers import (PublicRequestDTO, initials,
                                 build_public_request, ROLE_TO_REQUESTER)
from ctc.domain.config import NANO_PER_AIU
from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.domain.types import Request, Grant, Role


def test_initials():
    assert initials("Ada Lovelace") == "AL"
    assert initials("madonna") == "M"
    assert initials("") == "?"


def test_camel_alias_and_nano_output():
    conn = connect(":memory:"); init_db(conn); store = AccountingStore(conn)
    store.add_request(Request("r1", "c1", "u_ada", Role.CONSUMER,
                              100 * NANO_PER_AIU, "need", None, 1, 9999))
    store.add_grant(Grant("g1", "c1", "r1", "u_mb", "u_ada", 40 * NANO_PER_AIU, 5))
    users = {"u_ada": {"display_name": "Ada Lovelace"}}
    dto = build_public_request(store, lambda uid: users.get(uid), store.get_request("r1"), now=10)
    j = dto.model_dump(by_alias=True)
    assert j["requesterId"] == "u_ada"
    assert j["requesterName"] == "Ada Lovelace"
    assert j["initials"] == "AL"
    assert j["requesterRole"] == "noob"        # consumer -> noob
    assert j["amountNeeded"] == 100 * NANO_PER_AIU   # raw nano-AIU on the wire
    assert j["amountFunded"] == 40 * NANO_PER_AIU
    assert j["status"] == "partially_funded"
    assert j["donorCount"] == 1
