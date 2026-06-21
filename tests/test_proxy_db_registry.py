import importlib

from ctc.auth.crypto import derive_key
from ctc.auth.registry import AuthRegistry
from ctc.accounting.engine import AccountingEngine
from ctc.store.auth_store import AuthStore
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db


def test_build_attribution_db_path(tmp_path, monkeypatch):
    db = str(tmp_path / "ctc.smoke.db")
    conn = connect(db); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn))
    eng.start_cycle("c1", "June", 0, 10_000_000_000)
    eng.set_quota("c1", "u1", 1000)
    eng.set_pledge("c1", "u1", 500)
    store.upsert_user("u1", "octocat", "Octo", "giver", 1)
    reg = AuthRegistry(store, derive_key("sek"))
    _, token, _ = reg.issue_proxy_token("u1", now=2)
    reg.store_pat("u1", "github_pat_REAL", now=2)

    monkeypatch.setenv("CTC_DB_PATH", db)
    monkeypatch.setenv("CTC_SECRET_KEY", "sek")
    monkeypatch.delenv("CTC_IDENTITY_JSON", raising=False)
    monkeypatch.delenv("CTC_PATS_JSON", raising=False)

    proxy = importlib.import_module("proxy")
    attribution = proxy._build_attribution()
    assert attribution is not None
    ident = attribution.resolve_consumer(token)
    assert ident.user_id == "u1" and ident.is_giver is True
    src = attribution.select_source("c1", ident)
    assert src.giver_id == "u1" and src.pat == "github_pat_REAL"
