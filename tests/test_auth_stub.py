from ctc.auth.identity import (
    ConsumerIdentity, InMemoryIdentityProvider, InMemoryPatRegistry,
)


def test_identity_resolve_known_and_unknown():
    alice = ConsumerIdentity(user_id="alice", is_giver=True)
    idp = InMemoryIdentityProvider({"ghp_fake_alice": alice})
    assert idp.resolve("ghp_fake_alice") == alice
    assert idp.resolve("nope") is None


def test_pat_registry_lookup_and_listing():
    reg = InMemoryPatRegistry({"alice": "ghp_real_alice", "bob": "ghp_real_bob"})
    assert reg.pat_for("alice") == "ghp_real_alice"
    assert reg.pat_for("carol") is None
    assert sorted(reg.list_givers()) == ["alice", "bob"]
