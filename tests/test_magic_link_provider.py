import logging
import pytest
from ctc.store.db import connect, init_db
from ctc.store.auth_store import AuthStore
from ctc.auth.email_sender import ConsoleEmailSender
from ctc.auth.magic_link import EmailMagicLink


def _ml():
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    sender = ConsoleEmailSender(logging.getLogger("t"))
    return EmailMagicLink(store, secret="s3cr3t", app_origin="http://app", sender=sender, ttl_seconds=900)


def test_round_trip():
    ml = _ml()
    link = ml.start("a@b.com", now=1000)
    token = link.split("token=")[1]
    assert ml.verify(token, now=1100) == "a@b.com"


def test_expired_rejected():
    ml = _ml()
    token = ml.start("a@b.com", now=1000).split("token=")[1]
    with pytest.raises(ValueError):
        ml.verify(token, now=1000 + 901)


def test_single_use():
    ml = _ml()
    token = ml.start("a@b.com", now=1000).split("token=")[1]
    ml.verify(token, now=1100)
    with pytest.raises(ValueError):
        ml.verify(token, now=1101)


def test_tampered_signature_rejected():
    ml = _ml()
    token = ml.start("a@b.com", now=1000).split("token=")[1]
    tid = token.split(".")[0]
    with pytest.raises(ValueError):
        ml.verify(f"{tid}.deadbeef", now=1100)


def test_invalid_email_raises():
    ml = _ml()
    with pytest.raises(ValueError):
        ml.start("not-an-email", now=1000)
