import pytest
from ctc.auth.crypto import derive_key, encrypt, decrypt, fingerprint


def test_round_trip():
    key = derive_key("super-secret")
    ct, nonce = encrypt("github_pat_REAL", key)
    assert ct != b"github_pat_REAL"
    assert decrypt(ct, nonce, key) == "github_pat_REAL"


def test_wrong_key_fails():
    ct, nonce = encrypt("x", derive_key("k1"))
    with pytest.raises(Exception):
        decrypt(ct, nonce, derive_key("k2"))


def test_nonce_is_unique_per_encrypt():
    key = derive_key("k")
    _, n1 = encrypt("a", key)
    _, n2 = encrypt("a", key)
    assert n1 != n2


def test_fingerprint_stable_and_short():
    assert fingerprint("github_pat_X") == fingerprint("github_pat_X")
    assert len(fingerprint("github_pat_X")) == 8
