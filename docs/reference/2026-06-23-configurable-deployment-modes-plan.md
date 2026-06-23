# Configurable Deployment Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make four deployment characteristics configurable — website transport (https/http), auth mode (GHE OAuth / email magic-link), participants mode (givers_and_consumers / givers_only), and the automatic shared pool (on/off) — without touching the CLI/proxy data path.

**Architecture:** Two boot-time env switches (`CTC_WEB_TRANSPORT`, `CTC_AUTH_MODE`) validated at startup, and two live admin toggles (`participants_mode`, `shared_pool_enabled`) stored in the existing `settings` key/value table behind `EffectiveConfig`. Each axis is enforced at exactly one seam: web transport in Caddy + `CTC_APP_ORIGIN`; auth mode in `make_app` route wiring + a new email provider; participants & pool in `AttributionService.select_source` (plus pool-off ⇒ `default_pledge_pct` resolves to 0, so onboarding auto-pledge self-disables).

**Tech Stack:** Python 3.11 stdlib + `aiohttp` (control plane), `sqlite3` (store), `pytest` (tests), TypeScript + React + Vite (web), Caddy (TLS front).

## Global Constraints

- Runtime deps: stdlib + `aiohttp` only (email uses stdlib `smtplib`). No new pip deps.
- Credits are nano-AIU integers (`NANO_PER_AIU = 1_000_000_000`). Never change the metering contract.
- Never log or return a PAT or `CTC_SECRET_KEY`. Magic-link tokens are HMAC-signed with `CTC_SECRET_KEY`.
- Settings live in the existing `settings(key,value,updated_at,updated_by)` table; no schema-breaking migration. New tables are additive and created in `init_db`.
- Cookie `Secure` flag already follows `app_origin.startswith("https")` in `api_server.py` — do not add new cookie logic; drive it via `CTC_APP_ORIGIN` scheme.
- Web DTOs use `CamelModel` (snake_case server ↔ camelCase client) — follow `ctc/api/serializers.py`.
- Shipped defaults (fresh deploy): `CTC_AUTH_MODE=email`, `CTC_WEB_TRANSPORT=http`, `participants_mode=givers_only`, `shared_pool_enabled=off`. These change behavior on upgrade — call out in `.env.example` + deploy guide.
- Run tests from repo root with `pytest`. The suite is already green; keep it green after every task.

---

## Phase A — Config foundation

### Task 1: Deployment env config (boot-time enums)

**Files:**
- Create: `ctc/domain/deployment.py`
- Test: `tests/test_deployment_config.py`

**Interfaces:**
- Produces: `DeploymentConfig` frozen dataclass with fields `auth_mode: str` (`"email"|"ghe_oauth"`), `web_transport: str` (`"http"|"https"`), `email_backend: str` (`"console"|"smtp"`); classmethod `from_env(env: Mapping) -> DeploymentConfig` that validates and raises `ValueError` on an invalid value; defaults `auth_mode="email"`, `web_transport="http"`, `email_backend="console"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deployment_config.py
import pytest
from ctc.domain.deployment import DeploymentConfig


def test_defaults_match_shipped_target_shape():
    cfg = DeploymentConfig.from_env({})
    assert cfg.auth_mode == "email"
    assert cfg.web_transport == "http"
    assert cfg.email_backend == "console"


def test_reads_overrides():
    cfg = DeploymentConfig.from_env({
        "CTC_AUTH_MODE": "ghe_oauth",
        "CTC_WEB_TRANSPORT": "https",
        "CTC_EMAIL_BACKEND": "smtp",
    })
    assert cfg.auth_mode == "ghe_oauth"
    assert cfg.web_transport == "https"
    assert cfg.email_backend == "smtp"


@pytest.mark.parametrize("key,bad", [
    ("CTC_AUTH_MODE", "ldap"),
    ("CTC_WEB_TRANSPORT", "ftp"),
    ("CTC_EMAIL_BACKEND", "smtp2"),
])
def test_invalid_value_raises(key, bad):
    with pytest.raises(ValueError) as e:
        DeploymentConfig.from_env({key: bad})
    assert key in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_deployment_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ctc.domain.deployment'`

- [ ] **Step 3: Write minimal implementation**

```python
# ctc/domain/deployment.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

_AUTH_MODES = ("email", "ghe_oauth")
_WEB_TRANSPORTS = ("http", "https")
_EMAIL_BACKENDS = ("console", "smtp")


def _pick(env: Mapping, key: str, allowed: tuple[str, ...], default: str) -> str:
    v = (env.get(key) or default).strip().lower()
    if v not in allowed:
        raise ValueError(f"{key} must be one of {allowed!r}, got {v!r}")
    return v


@dataclass(frozen=True)
class DeploymentConfig:
    auth_mode: str = "email"
    web_transport: str = "http"
    email_backend: str = "console"

    @classmethod
    def from_env(cls, env: Mapping) -> "DeploymentConfig":
        return cls(
            auth_mode=_pick(env, "CTC_AUTH_MODE", _AUTH_MODES, "email"),
            web_transport=_pick(env, "CTC_WEB_TRANSPORT", _WEB_TRANSPORTS, "http"),
            email_backend=_pick(env, "CTC_EMAIL_BACKEND", _EMAIL_BACKENDS, "console"),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_deployment_config.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add ctc/domain/deployment.py tests/test_deployment_config.py
git commit -m "feat(config): DeploymentConfig boot-time enums (auth/web-transport/email)"
```

---

### Task 2: Live settings — `participants_mode` + `shared_pool_enabled`

**Files:**
- Modify: `ctc/domain/config.py` (add two fields)
- Modify: `ctc/domain/settings.py` (`EFFECTIVE_KEYS`, `EffectiveConfig`, `effective_view`, `validate_patch`)
- Test: `tests/test_settings_modes.py`

**Interfaces:**
- Consumes: `EffectiveConfig(store)` from Task's modified `ctc/domain/settings.py`.
- Produces: `EffectiveConfig.participants_mode -> str`, `EffectiveConfig.shared_pool_enabled -> bool`; `EffectiveConfig.default_pledge_pct` returns `0` when `shared_pool_enabled` is False; `validate_patch` accepts `participants_mode` (`"givers_only"|"givers_and_consumers"`) and `shared_pool_enabled` (`"on"|"off"`/bool), rejects invalid values. New `Config` fields `participants_mode: str` (default from `CTC_PARTICIPANTS_MODE`, else `"givers_only"`) and `shared_pool_enabled: bool` (default from `CTC_SHARED_POOL`, else `False`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings_modes.py
import pytest
from ctc.store.db import connect, init_db
from ctc.store.settings_store import SettingsStore
from ctc.domain.settings import EffectiveConfig, effective_view, validate_patch


def _ec():
    conn = connect(":memory:")
    init_db(conn)
    store = SettingsStore(conn)
    return EffectiveConfig(store), store


def test_mode_defaults_are_target_shape():
    ec, _ = _ec()
    assert ec.participants_mode == "givers_only"
    assert ec.shared_pool_enabled is False


def test_pool_off_forces_default_pledge_zero():
    ec, _ = _ec()
    assert ec.shared_pool_enabled is False
    assert ec.default_pledge_pct == 0


def test_db_override_wins(monkeypatch):
    ec, store = _ec()
    store.set_many({"shared_pool_enabled": "on",
                    "participants_mode": "givers_and_consumers"}, "admin", 1)
    assert ec.shared_pool_enabled is True
    assert ec.participants_mode == "givers_and_consumers"


def test_validate_patch_accepts_modes():
    out = validate_patch({"participants_mode": "givers_only",
                          "shared_pool_enabled": "off"})
    assert out["participants_mode"] == "givers_only"
    assert out["shared_pool_enabled"] == "off"


@pytest.mark.parametrize("patch", [
    {"participants_mode": "nope"},
    {"shared_pool_enabled": "maybe"},
])
def test_validate_patch_rejects_bad_modes(patch):
    with pytest.raises(ValueError):
        validate_patch(patch)


def test_effective_view_includes_modes():
    ec, store = _ec()
    view = effective_view(ec, store)
    assert view["participants_mode"]["value"] == "givers_only"
    assert view["shared_pool_enabled"]["value"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings_modes.py -v`
Expected: FAIL (`AttributeError: 'EffectiveConfig' object has no attribute 'participants_mode'`)

- [ ] **Step 3: Write minimal implementation**

In `ctc/domain/config.py`, add to the `Config` dataclass (after `default_pledge_pct`):

```python
    participants_mode: str = field(
        default_factory=lambda: os.environ.get("CTC_PARTICIPANTS_MODE", "givers_only"))
    shared_pool_enabled: bool = field(
        default_factory=lambda: os.environ.get("CTC_SHARED_POOL", "off").strip().lower()
        in ("1", "on", "true", "yes"))
```

In `ctc/domain/settings.py`, extend `EFFECTIVE_KEYS`:

```python
EFFECTIVE_KEYS = [
    "free_allowance_aiu", "default_pledge_pct",
    "request_expiry_hours", "request_expiry_max_hours", "credit_to_euro_rate",
    "participants_mode", "shared_pool_enabled",
]
```

Add properties to `EffectiveConfig` (and gate `default_pledge_pct`):

```python
    @property
    def shared_pool_enabled(self) -> bool:
        v = self._raw("shared_pool_enabled")
        if v is None:
            return self.base.shared_pool_enabled
        return str(v).strip().lower() in ("1", "on", "true", "yes")

    @property
    def participants_mode(self) -> str:
        v = self._raw("participants_mode")
        return v if v is not None else self.base.participants_mode
```

Change the existing `default_pledge_pct` property to return 0 when the pool is off:

```python
    @property
    def default_pledge_pct(self) -> int:
        if not self.shared_pool_enabled:
            return 0
        v = self._raw("default_pledge_pct")
        return int(v) if v is not None else self.base.default_pledge_pct
```

Extend `effective_view` (add two entries to the returned dict):

```python
        "participants_mode": {"value": ec.participants_mode,
                              "is_override": "participants_mode" in raw},
        "shared_pool_enabled": {"value": ec.shared_pool_enabled,
                                "is_override": "shared_pool_enabled" in raw},
```

In `validate_patch`, before the `for k, v in patch.items()` loop, handle the two new keys (and skip them in the numeric/float branch):

```python
    _MODES = {"participants_mode": ("givers_only", "givers_and_consumers")}
    _BOOLS = ("shared_pool_enabled",)
```

Then inside the loop, add branches ahead of the `credit_to_euro_rate` check:

```python
        if k in _MODES:
            if str(v) not in _MODES[k]:
                raise ValueError(f"{k} must be one of {_MODES[k]!r}")
            out[k] = str(v); continue
        if k in _BOOLS:
            s = str(v).strip().lower()
            if s not in ("on", "off", "true", "false", "1", "0"):
                raise ValueError(f"{k} must be on/off")
            out[k] = "on" if s in ("on", "true", "1") else "off"; continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_settings_modes.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ctc/domain/config.py ctc/domain/settings.py tests/test_settings_modes.py
git commit -m "feat(settings): participants_mode + shared_pool_enabled live settings"
```

---

## Phase B — Accounting gates (Axis 3 + Axis 4)

`AttributionService` is constructed with `engine` whose `engine.config` is an `EffectiveConfig` (see `api_server.build_from_env`). The gates read `self.engine.config.shared_pool_enabled` and `self.engine.config.participants_mode`.

### Task 3: Pool-off gate in `select_source`

**Files:**
- Modify: `ctc/routing/attribution.py:34-55` (`select_source`)
- Test: `tests/test_attribution_modes.py`

**Interfaces:**
- Consumes: `EffectiveConfig.shared_pool_enabled` (Task 2).
- Produces: when pool disabled, `select_source` never returns a `Source` with `Bucket.POOL`; givers still resolve OWN→GRANT, consumers resolve GRANT-only.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_attribution_modes.py
from ctc.routing.attribution import AttributionService
from ctc.auth.identity import ConsumerIdentity, InMemoryIdentityProvider, InMemoryPatRegistry
from ctc.accounting.engine import AccountingEngine
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db
from ctc.domain.types import Bucket


class _Cfg:
    def __init__(self, pool, mode): self.shared_pool_enabled = pool; self.participants_mode = mode
    free_allowance = 300 * 1_000_000_000
    default_pledge_pct = 0


def _engine(pool=True, mode="givers_and_consumers"):
    conn = connect(":memory:"); init_db(conn)
    eng = AccountingEngine(AccountingStore(conn), config=_Cfg(pool, mode))
    cyc = eng.ensure_active_cycle(1000)
    return eng, cyc


def test_pool_off_consumer_with_no_grant_gets_no_source():
    eng, cyc = _engine(pool=False)
    # a giver exists with pledge, but pool is off → consumer cannot draw pool
    eng.set_quota(cyc.id, "g1", 100 * 1_000_000_000)
    eng.set_pledge(cyc.id, "g1", 50 * 1_000_000_000)
    pats = InMemoryPatRegistry({"g1": "pat_g1"})
    idp = InMemoryIdentityProvider({"tokC": ConsumerIdentity("c1", is_giver=False)})
    svc = AttributionService(eng, idp, pats)
    assert svc.select_source(cyc.id, ConsumerIdentity("c1", is_giver=False)) is None


def test_pool_on_consumer_draws_pool():
    eng, cyc = _engine(pool=True)
    eng.set_quota(cyc.id, "g1", 100 * 1_000_000_000)
    eng.set_pledge(cyc.id, "g1", 50 * 1_000_000_000)
    pats = InMemoryPatRegistry({"g1": "pat_g1"})
    svc = AttributionService(eng, InMemoryIdentityProvider({}), pats)
    src = svc.select_source(cyc.id, ConsumerIdentity("c1", is_giver=False))
    assert src is not None and src.bucket == Bucket.POOL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_attribution_modes.py -v`
Expected: FAIL — `test_pool_off_consumer_with_no_grant_gets_no_source` returns a POOL source (pool not yet gated).

- [ ] **Step 3: Write minimal implementation**

In `ctc/routing/attribution.py`, edit the consumer branch of `select_source`. Replace:

```python
        # non-PAT consumer: GRANT -> POOL
        grant = self._grant_source(cycle_id, uid)
        if grant is not None:
            return grant
        if self.engine.allowance_remaining(cycle_id, uid) > 0:
```

with:

```python
        # non-PAT consumer: GRANT -> POOL (POOL only when the shared pool is enabled)
        grant = self._grant_source(cycle_id, uid)
        if grant is not None:
            return grant
        if getattr(self.engine.config, "shared_pool_enabled", True) \
                and self.engine.allowance_remaining(cycle_id, uid) > 0:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_attribution_modes.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add ctc/routing/attribution.py tests/test_attribution_modes.py
git commit -m "feat(attribution): gate POOL bucket behind shared_pool_enabled"
```

---

### Task 4: Givers-only gate in `select_source`

**Files:**
- Modify: `ctc/routing/attribution.py` (`select_source`, top of method)
- Test: `tests/test_attribution_modes.py` (append)

**Interfaces:**
- Consumes: `EffectiveConfig.participants_mode` (Task 2).
- Produces: when `participants_mode == "givers_only"`, a non-giver `ConsumerIdentity` yields `None` (→ proxy 402).

- [ ] **Step 1: Write the failing test (append to tests/test_attribution_modes.py)**

```python
def test_givers_only_blocks_non_giver_even_when_pool_would_fund():
    # pool ON so that WITHOUT the givers_only gate the non-giver would resolve to
    # POOL. The gate must make it None regardless — this is the genuine red.
    eng, cyc = _engine(pool=True, mode="givers_only")
    eng.set_quota(cyc.id, "g1", 100 * 1_000_000_000)
    eng.set_pledge(cyc.id, "g1", 50 * 1_000_000_000)
    pats = InMemoryPatRegistry({"g1": "pat_g1"})
    svc = AttributionService(eng, InMemoryIdentityProvider({}), pats)
    assert svc.select_source(cyc.id, ConsumerIdentity("c1", is_giver=False)) is None


def test_givers_and_consumers_pool_on_still_funds_non_giver():
    # Control: same setup but mode allows consumers → POOL source returned.
    eng, cyc = _engine(pool=True, mode="givers_and_consumers")
    eng.set_quota(cyc.id, "g1", 100 * 1_000_000_000)
    eng.set_pledge(cyc.id, "g1", 50 * 1_000_000_000)
    pats = InMemoryPatRegistry({"g1": "pat_g1"})
    svc = AttributionService(eng, InMemoryIdentityProvider({}), pats)
    src = svc.select_source(cyc.id, ConsumerIdentity("c1", is_giver=False))
    assert src is not None and src.bucket == Bucket.POOL


def test_givers_only_allows_giver_with_own_credit():
    eng, cyc = _engine(pool=False, mode="givers_only")
    eng.set_quota(cyc.id, "g1", 100 * 1_000_000_000)
    pats = InMemoryPatRegistry({"g1": "pat_g1"})
    svc = AttributionService(eng, InMemoryIdentityProvider({}), pats)
    src = svc.select_source(cyc.id, ConsumerIdentity("g1", is_giver=True))
    assert src is not None and src.bucket == Bucket.OWN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_attribution_modes.py::test_givers_only_blocks_non_giver_even_when_pool_would_fund -v`
Expected: FAIL — without the gate the non-giver resolves to a `POOL` source (pool is on), so the `is None` assertion fails. This is the genuine red the gate fixes.

- [ ] **Step 3: Write minimal implementation**

In `select_source`, add at the very top (before `uid = consumer.user_id`):

```python
        if getattr(self.engine.config, "participants_mode", "givers_and_consumers") \
                == "givers_only" and not consumer.is_giver:
            return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_attribution_modes.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add ctc/routing/attribution.py tests/test_attribution_modes.py
git commit -m "feat(attribution): givers_only blocks non-PAT consumers"
```

---

## Phase C — Auth mode (Axis 2): email magic-link

### Task 5: `magic_links` table + store

**Files:**
- Modify: `ctc/store/db.py` (add `magic_links` to `SCHEMA`)
- Modify: `ctc/store/auth_store.py` (add magic-link methods)
- Test: `tests/test_magic_link_store.py`

**Interfaces:**
- Produces on `AuthStore`: `add_magic_link(id, email, expires_at, created_at)`, `get_magic_link(id) -> Row|None` (cols `id,email,expires_at,consumed_at,created_at`), `consume_magic_link(id, now) -> bool` (sets `consumed_at`, returns False if already consumed).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_magic_link_store.py
from ctc.store.db import connect, init_db
from ctc.store.auth_store import AuthStore


def _store():
    conn = connect(":memory:"); init_db(conn)
    return AuthStore(conn)


def test_add_and_get():
    s = _store()
    s.add_magic_link("id1", "a@b.com", expires_at=100, created_at=10)
    row = s.get_magic_link("id1")
    assert row["email"] == "a@b.com" and row["consumed_at"] is None


def test_consume_is_single_use():
    s = _store()
    s.add_magic_link("id1", "a@b.com", expires_at=100, created_at=10)
    assert s.consume_magic_link("id1", now=20) is True
    assert s.consume_magic_link("id1", now=21) is False
    assert s.get_magic_link("id1")["consumed_at"] == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_magic_link_store.py -v`
Expected: FAIL (`AttributeError: ... add_magic_link`)

- [ ] **Step 3: Write minimal implementation**

Add to `SCHEMA` in `ctc/store/db.py` (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS magic_links (
  id          TEXT PRIMARY KEY,
  email       TEXT NOT NULL,
  expires_at  INTEGER NOT NULL,
  consumed_at INTEGER,
  created_at  INTEGER NOT NULL
);
```

Add to `AuthStore` in `ctc/store/auth_store.py`:

```python
    def add_magic_link(self, id, email, expires_at, created_at):
        self.conn.execute(
            "INSERT INTO magic_links (id, email, expires_at, created_at) VALUES (?,?,?,?)",
            (id, email, expires_at, created_at),
        )

    def get_magic_link(self, id):
        return self.conn.execute(
            "SELECT id, email, expires_at, consumed_at, created_at FROM magic_links WHERE id=?",
            (id,),
        ).fetchone()

    def consume_magic_link(self, id, now) -> bool:
        cur = self.conn.execute(
            "UPDATE magic_links SET consumed_at=? WHERE id=? AND consumed_at IS NULL",
            (now, id),
        )
        return cur.rowcount == 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_magic_link_store.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add ctc/store/db.py ctc/store/auth_store.py tests/test_magic_link_store.py
git commit -m "feat(store): magic_links table + single-use consume"
```

---

### Task 6: Email sender seam

**Files:**
- Create: `ctc/auth/email_sender.py`
- Test: `tests/test_email_sender.py`

**Interfaces:**
- Produces: `ConsoleEmailSender(log)` with `send_magic_link(email, link)` that logs the link; `SmtpEmailSender(host, port, user, password, sender, starttls=True)` with the same method building a `MIMEText` and calling `smtplib.SMTP`; `email_sender_from_env(env, log) -> EmailSender` selecting by `CTC_EMAIL_BACKEND`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_sender.py
import logging
from ctc.auth.email_sender import ConsoleEmailSender, email_sender_from_env, SmtpEmailSender


def test_console_logs_link(caplog):
    sender = ConsoleEmailSender(logging.getLogger("test"))
    with caplog.at_level(logging.INFO):
        sender.send_magic_link("a@b.com", "http://x/auth/magic?token=zzz")
    assert "a@b.com" in caplog.text and "auth/magic?token=zzz" in caplog.text


def test_from_env_defaults_to_console():
    s = email_sender_from_env({}, logging.getLogger("t"))
    assert isinstance(s, ConsoleEmailSender)


def test_from_env_smtp_selects_smtp():
    s = email_sender_from_env({
        "CTC_EMAIL_BACKEND": "smtp", "CTC_SMTP_HOST": "mail", "CTC_SMTP_PORT": "25",
        "CTC_SMTP_FROM": "ctc@x",
    }, logging.getLogger("t"))
    assert isinstance(s, SmtpEmailSender)


def test_smtp_builds_and_sends(monkeypatch):
    sent = {}
    class FakeSMTP:
        def __init__(self, host, port): sent["addr"] = (host, port)
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): sent["tls"] = True
        def login(self, u, p): sent["login"] = (u, p)
        def send_message(self, msg): sent["msg"] = msg
    monkeypatch.setattr("ctc.auth.email_sender.smtplib.SMTP", FakeSMTP)
    SmtpEmailSender("mail", 587, "u", "p", "ctc@x").send_magic_link("a@b.com", "http://link")
    assert sent["addr"] == ("mail", 587)
    assert sent["msg"]["To"] == "a@b.com"
    assert "http://link" in sent["msg"].get_content()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_email_sender.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

```python
# ctc/auth/email_sender.py
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Mapping, Protocol


class EmailSender(Protocol):
    def send_magic_link(self, email: str, link: str) -> None: ...


class ConsoleEmailSender:
    def __init__(self, log):
        self.log = log

    def send_magic_link(self, email: str, link: str) -> None:
        self.log.info("magic-link for %s: %s", email, link)


class SmtpEmailSender:
    def __init__(self, host, port, user=None, password=None, sender=None, starttls=True):
        self.host, self.port = host, int(port)
        self.user, self.password = user, password
        self.sender = sender or user or "ctc@localhost"
        self.starttls = starttls

    def send_magic_link(self, email: str, link: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = email
        msg["Subject"] = "Your CTC sign-in link"
        msg.set_content(f"Click to sign in (expires shortly):\n\n{link}\n")
        with smtplib.SMTP(self.host, self.port) as s:
            if self.starttls:
                s.starttls()
            if self.user:
                s.login(self.user, self.password or "")
            s.send_message(msg)


def email_sender_from_env(env: Mapping, log) -> EmailSender:
    if (env.get("CTC_EMAIL_BACKEND") or "console").strip().lower() == "smtp":
        return SmtpEmailSender(
            env["CTC_SMTP_HOST"], env.get("CTC_SMTP_PORT", "587"),
            env.get("CTC_SMTP_USER"), env.get("CTC_SMTP_PASS"),
            env.get("CTC_SMTP_FROM"),
            starttls=(env.get("CTC_SMTP_STARTTLS", "1").strip().lower() in ("1", "true", "on")),
        )
    return ConsoleEmailSender(log)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_email_sender.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ctc/auth/email_sender.py tests/test_email_sender.py
git commit -m "feat(auth): EmailSender seam (console + smtp)"
```

---

### Task 7: Magic-link provider (mint + verify)

**Files:**
- Create: `ctc/auth/magic_link.py`
- Test: `tests/test_magic_link_provider.py`

**Interfaces:**
- Consumes: `AuthStore` magic-link methods (Task 5).
- Produces: `EmailMagicLink(store, secret, app_origin, sender, ttl_seconds=900)` with:
  - `start(email, now) -> str` — validates email shape (raises `ValueError`), mints id, stores row, returns the full link `"{app_origin}/auth/magic?token={id}.{sig}"`, and calls `sender.send_magic_link`.
  - `verify(token, now) -> str` — returns the email on success; raises `ValueError("link invalid or expired")` on bad signature / unknown / expired / already-consumed. Marks consumed on success.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_magic_link_provider.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_magic_link_provider.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

```python
# ctc/auth/magic_link.py
from __future__ import annotations

import hashlib
import hmac
import re
import uuid

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _sign(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


class EmailMagicLink:
    def __init__(self, store, secret, app_origin, sender, ttl_seconds=900):
        self.store = store
        self.secret = secret
        self.app_origin = app_origin.rstrip("/")
        self.sender = sender
        self.ttl = ttl_seconds

    def start(self, email: str, now: int) -> str:
        email = (email or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("invalid email")
        tid = uuid.uuid4().hex
        self.store.add_magic_link(tid, email, expires_at=now + self.ttl, created_at=now)
        token = f"{tid}.{_sign(self.secret, tid)}"
        link = f"{self.app_origin}/auth/magic?token={token}"
        self.sender.send_magic_link(email, link)
        return link

    def verify(self, token: str, now: int) -> str:
        tid, _, sig = (token or "").partition(".")
        if not tid or not hmac.compare_digest(_sign(self.secret, tid), sig):
            raise ValueError("link invalid or expired")
        row = self.store.get_magic_link(tid)
        if row is None or row["expires_at"] < now:
            raise ValueError("link invalid or expired")
        if not self.store.consume_magic_link(tid, now):
            raise ValueError("link invalid or expired")
        return row["email"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_magic_link_provider.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add ctc/auth/magic_link.py tests/test_magic_link_provider.py
git commit -m "feat(auth): email magic-link provider (mint/verify/single-use)"
```

---

### Task 8: Wire auth mode into `make_app` + `/api/config`

**Files:**
- Modify: `api_server.py` (`make_app` signature + route wiring + `build_from_env`)
- Test: `tests/test_auth_mode_routes.py`

**Interfaces:**
- Consumes: `EmailMagicLink` (Task 7), `DeploymentConfig` (Task 1), `email_sender_from_env` (Task 6).
- Produces: `make_app(..., deployment, magic_link=None)` registers OAuth routes when `deployment.auth_mode == "ghe_oauth"`, else email routes `POST /auth/email` (`{email}` → `204`) and `GET /auth/magic?token=…` (verify → session cookie → redirect). Adds unauthenticated `GET /api/config -> {"authMode": ...}`. `/api/me` payload gains `auth_mode`, `web_transport`, `participants_mode`, `shared_pool_enabled`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth_mode_routes.py
import time
import pytest
from aiohttp import web
from api_server import make_app
from ctc.store.db import connect, init_db
from ctc.store.auth_store import AuthStore
from ctc.store.accounting_store import AccountingStore
from ctc.store.settings_store import SettingsStore
from ctc.accounting.engine import AccountingEngine
from ctc.domain.settings import EffectiveConfig
from ctc.domain.deployment import DeploymentConfig
from ctc.auth.registry import AuthRegistry
from ctc.auth.sessions import SessionService
from ctc.auth.crypto import derive_key
from ctc.auth.email_sender import ConsoleEmailSender
from ctc.auth.magic_link import EmailMagicLink
import logging


def _app(auth_mode):
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    ec = EffectiveConfig(SettingsStore(conn))
    engine = AccountingEngine(AccountingStore(conn), config=ec)
    engine.ensure_active_cycle(int(time.time()))
    reg = AuthRegistry(store, derive_key("k" * 32))
    sessions = SessionService(store, secret="k" * 32)
    dep = DeploymentConfig(auth_mode=auth_mode, web_transport="http", email_backend="console")
    ml = EmailMagicLink(store, "k" * 32, "http://app", ConsoleEmailSender(logging.getLogger("t")))
    return make_app(store=store, engine=engine, registry=reg, sessions=sessions,
                    oauth=None, http_get_user=None, secret="k" * 32, app_origin="http://app",
                    deployment=dep, magic_link=ml, ca_cert_path="/nonexistent.pem")
    # ca_cert_path is a non-existent path on purpose: ca_fingerprint_sha256 returns
    # None for an unreadable file, so make_app constructs cleanly without a cert.


async def test_api_config_reports_auth_mode(aiohttp_client):
    client = await aiohttp_client(_app("email"))
    r = await client.get("/api/config")
    assert r.status == 200
    assert (await r.json())["authMode"] == "email"


async def test_email_login_sets_session(aiohttp_client):
    client = await aiohttp_client(_app("email"))
    r = await client.post("/auth/email", json={"email": "a@b.com"})
    assert r.status == 204
    # console sender logged the link; in test, mint+verify directly via the app store is covered by provider tests.


async def test_oauth_mode_has_no_email_route(aiohttp_client):
    client = await aiohttp_client(_app("ghe_oauth"))
    r = await client.post("/auth/email", json={"email": "a@b.com"})
    assert r.status == 404
```

> `aiohttp_client` is the `pytest-aiohttp` fixture; check `tests/test_api_server.py` for the existing pattern and reuse its helpers if present.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth_mode_routes.py -v`
Expected: FAIL — `make_app` has no `deployment`/`magic_link` params yet.

- [ ] **Step 3: Write minimal implementation**

In `api_server.py`, change `make_app` to accept `deployment` and `magic_link=None`. Make the `oauth` param optional. Replace the unconditional OAuth route registration with mode-conditional wiring:

```python
    async def auth_email_start(req):
        body = await req.json()
        try:
            magic_link.start((body or {}).get("email", ""), now())
        except ValueError:
            pass  # do not reveal validity / deliverability
        return web.Response(status=204)

    async def auth_magic(req):
        try:
            email = magic_link.verify(req.query.get("token", ""), now())
        except ValueError:
            raise web.HTTPBadRequest(text="link invalid or expired")
        user = store.get_user_by_login(email)
        if user is None:
            uid = uuid.uuid4().hex
            store.upsert_user(uid, email, email, "consumer", now())
            user = store.get_user_by_id(uid)
        cookie_val = sessions.create(user["id"], now())
        resp = web.HTTPFound(app_origin)
        resp.set_cookie(COOKIE, cookie_val, httponly=True, samesite="Lax",
                        secure=app_origin.startswith("https"))
        raise resp

    async def api_config(req):
        return web.json_response({"authMode": deployment.auth_mode})

    if deployment.auth_mode == "ghe_oauth":
        app.add_routes([
            web.get("/auth/login", auth_login),
            web.get("/auth/callback", auth_callback),
        ])
    else:
        app.add_routes([
            web.post("/auth/email", auth_email_start),
            web.get("/auth/magic", auth_magic),
        ])
    app.add_routes([web.get("/api/config", api_config)])
```

Extend the `api_me` response dict with:

```python
            "auth_mode": deployment.auth_mode,
            "web_transport": deployment.web_transport,
            "participants_mode": _effective_config.participants_mode,
            "shared_pool_enabled": _effective_config.shared_pool_enabled,
```

(Move the `_effective_config` construction above `api_me`, or pass it in; it is already built later in `make_app` — relocate that block before the route handlers.)

In `build_from_env`, build `deployment = DeploymentConfig.from_env(os.environ)`, build `magic_link` only in email mode:

```python
    from ctc.domain.deployment import DeploymentConfig
    deployment = DeploymentConfig.from_env(os.environ)
    oauth = None
    magic_link = None
    if deployment.auth_mode == "ghe_oauth":
        oauth = GheOAuth(os.environ["GHE_OAUTH_CLIENT_ID"], os.environ["GHE_OAUTH_CLIENT_SECRET"],
                         os.environ["GHE_OAUTH_REDIRECT_URI"], base, http=AiohttpJson(session))
    else:
        import logging
        from ctc.auth.email_sender import email_sender_from_env
        from ctc.auth.magic_link import EmailMagicLink
        sender = email_sender_from_env(os.environ, logging.getLogger("ctc.email"))
        magic_link = EmailMagicLink(store, secret, os.environ.get("CTC_APP_ORIGIN", "/"), sender)
```

Pass `deployment=deployment, magic_link=magic_link` to `make_app`. Guard the OAuth-only env reads (`base`, `api_base`, `GHE_OAUTH_*`) so they are not required in email mode — read `base`/`api_base` only when needed for OAuth, but keep `api_base` + `http_get_user` (PAT validation needs `/copilot_internal/user` regardless of auth mode).

> Implementer note: `http_get_user` and `api_base` are still required in email mode (PAT onboarding calls them). Only the `GHE_OAUTH_*` + web `base` for login are OAuth-only. Keep `GHE_API_BASE` required.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth_mode_routes.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all pass. (If existing `tests/test_api_server.py` calls `make_app` without `deployment`, update those call sites to pass a default `DeploymentConfig(auth_mode="ghe_oauth", web_transport="https", email_backend="console")` so legacy tests keep exercising OAuth.)

- [ ] **Step 6: Commit**

```bash
git add api_server.py tests/test_auth_mode_routes.py tests/test_api_server.py
git commit -m "feat(auth): wire auth_mode into make_app, add /api/config + mode flags on /api/me"
```

---

### Task 9: Startup validation wired

**Files:**
- Modify: `api_server.py` (`build_from_env` — call `DeploymentConfig.from_env` early; assert `CTC_APP_ORIGIN` scheme matches `web_transport`)
- Test: `tests/test_startup_validation.py`

**Interfaces:**
- Consumes: `DeploymentConfig.from_env` (Task 1).
- Produces: invalid enum env → process refuses to build the app (`ValueError`); `CTC_WEB_TRANSPORT` inconsistent with `CTC_APP_ORIGIN` scheme → `ValueError` with a clear message.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_startup_validation.py
import pytest
from ctc.domain.deployment import DeploymentConfig


def test_app_origin_scheme_consistency_helper():
    from api_server import assert_transport_consistent
    # https transport + http origin → error
    with pytest.raises(ValueError):
        assert_transport_consistent(DeploymentConfig(web_transport="https",
                                                     auth_mode="email", email_backend="console"),
                                    "http://app")
    # consistent → ok
    assert_transport_consistent(DeploymentConfig(web_transport="http",
                                                 auth_mode="email", email_backend="console"),
                                "http://app") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_startup_validation.py -v`
Expected: FAIL (`ImportError: cannot import name 'assert_transport_consistent'`).

- [ ] **Step 3: Write minimal implementation**

Add to `api_server.py` (module level):

```python
def assert_transport_consistent(deployment, app_origin) -> None:
    origin_https = app_origin.startswith("https")
    if (deployment.web_transport == "https") != origin_https:
        raise ValueError(
            f"CTC_WEB_TRANSPORT={deployment.web_transport} but CTC_APP_ORIGIN="
            f"{app_origin!r}; scheme must match")
```

Call it in `build_from_env` after constructing `deployment` and reading `app_origin`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_startup_validation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api_server.py tests/test_startup_validation.py
git commit -m "feat(config): validate web_transport ↔ app_origin scheme at startup"
```

---

## Phase D — Admin & frontend exposure

### Task 10: Admin settings — surface modes (editable) + boot config (read-only)

**Files:**
- Modify: `ctc/api/admin_routes.py` (`get_settings` returns boot config too; `patch_settings` already routes through `validate_patch`)
- Modify: `api_server.py` (`register_admin_routes(...)` call — pass `deployment`)
- Test: `tests/test_admin_routes.py` (append)

**Interfaces:**
- Consumes: `effective_view` (now includes modes, Task 2), `DeploymentConfig` (Task 1).
- Produces: `GET /api/admin/settings` payload includes `participants_mode` + `shared_pool_enabled` (editable, with `is_override`) and a `boot` object `{"auth_mode":..,"web_transport":..,"email_backend":..,"source":"env"}`. `PATCH` with `{"shared_pool_enabled":"on"}` persists and the next `GET` reflects it.

- [ ] **Step 1: Write the failing test (append to tests/test_admin_routes.py, mirroring its existing fixtures)**

```python
async def test_admin_settings_includes_modes_and_boot(admin_client):
    r = await admin_client.get("/api/admin/settings")
    body = await r.json()
    assert body["participants_mode"]["value"] == "givers_only"
    assert body["shared_pool_enabled"]["value"] is False
    assert body["boot"]["auth_mode"] in ("email", "ghe_oauth")
    assert body["boot"]["source"] == "env"


async def test_admin_can_toggle_pool(admin_client):
    await admin_client.patch("/api/admin/settings", json={"shared_pool_enabled": "on"})
    r = await admin_client.get("/api/admin/settings")
    assert (await r.json())["shared_pool_enabled"]["value"] is True
```

> Reuse the existing admin-authenticated client fixture in `tests/test_admin_routes.py`. If `register_admin_routes` does not yet receive `deployment`, thread it through (see Step 3).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_admin_routes.py -k modes_and_boot -v`
Expected: FAIL (`KeyError: 'boot'`).

- [ ] **Step 3: Write minimal implementation**

In `ctc/api/admin_routes.py`, add `deployment` to `register_admin_routes(...)` params and to `get_settings`:

```python
    @admin_only
    async def get_settings(req, _admin):
        view = effective_view(effective_config, settings_store)
        view["boot"] = {"auth_mode": deployment.auth_mode,
                        "web_transport": deployment.web_transport,
                        "email_backend": deployment.email_backend,
                        "source": "env"}
        return web.json_response(view)
```

In `api_server.py`, pass `deployment=deployment` into the `register_admin_routes(...)` call.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_admin_routes.py -k "modes_and_boot or toggle_pool" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ctc/api/admin_routes.py api_server.py tests/test_admin_routes.py
git commit -m "feat(admin): expose mode toggles + read-only boot config in settings"
```

---

### Task 11: Frontend — auth screen by mode + `/api/config`

**Files:**
- Modify: `web/src/api/CtcApi.ts` (add `getConfig()` + extend `me` type), `web/src/api/HttpCtcApi.ts`, `web/src/api/mockApi.ts`
- Modify: `web/src/screens/Auth/AuthScreen.tsx`
- Test: `web/tests/` (follow existing Playwright/unit pattern in `web/tests`)

**Interfaces:**
- Consumes: `GET /api/config` (Task 8), `/api/me` mode flags (Task 8).
- Produces: `CtcApi.getConfig(): Promise<{ authMode: "email" | "ghe_oauth" }>`; `AuthScreen` renders an email-entry form (posting to `/auth/email`) when `authMode === "email"`, else the existing "Sign in with GitHub" button.

- [ ] **Step 1: Add the API method (type-first)**

In `web/src/api/CtcApi.ts`, add to the `CtcApi` interface:

```ts
  getConfig(): Promise<{ authMode: "email" | "ghe_oauth" }>;
  startEmailLogin(email: string): Promise<void>;
```

In `web/src/api/HttpCtcApi.ts`, implement using the existing `http` helper (grep for how other GETs/POSTs are written there):

```ts
  getConfig() { return http.get<{ authMode: "email" | "ghe_oauth" }>("/api/config"); }
  startEmailLogin(email: string) { return http.post<void>("/auth/email", { email }); }
```

In `web/src/api/mockApi.ts`, return `{ authMode: "email" }` and a no-op for `startEmailLogin`.

- [ ] **Step 2: Build + typecheck**

Run: `cd web && npm run build`
Expected: passes (no TS errors). If `me`'s type is declared in `CtcApi.ts`/`domain/types.ts`, add `authMode`, `webTransport`, `participantsMode`, `sharedPoolEnabled` to it.

- [ ] **Step 3: Render the email form in `AuthScreen.tsx`**

Fetch config on mount (use the existing `useAsync` store hook — grep `useAsync` usage). When `authMode === "email"`, show an `Input` + `Button` (existing components) that calls `api.startEmailLogin(email)` and then shows a "Check your email for a sign-in link" confirmation. Otherwise render the current GitHub button unchanged.

- [ ] **Step 4: Verify in the browser**

Run: `cd web && npm run dev`, open the app with the mock API; confirm the email form renders and submitting shows the confirmation. (No backend needed — mockApi.)

- [ ] **Step 5: Commit**

```bash
git add web/src/api/CtcApi.ts web/src/api/HttpCtcApi.ts web/src/api/mockApi.ts web/src/screens/Auth/AuthScreen.tsx web/src/domain/types.ts
git commit -m "feat(web): email-vs-oauth auth screen driven by /api/config"
```

---

### Task 12: Frontend — hide pool/pledge UI + add-a-license gating + admin mode toggles

**Files:**
- Modify: `web/src/screens/Dashboard/DashboardScreen.tsx`, `web/src/screens/Profile/*` (pledge/pool widgets), `web/src/screens/Admin/AdminScreen.tsx`
- Modify: `web/src/store/AppContext.tsx` (expose mode flags from `me`)

**Interfaces:**
- Consumes: `me.sharedPoolEnabled`, `me.participantsMode` (Task 8).
- Produces: pledge/pool widgets render only when `sharedPoolEnabled`; when `participantsMode === "givers_only"` and the user has no PAT, the dashboard shows an "Add a license to continue" prompt; `AdminScreen` shows two toggles (participants mode, shared pool) that PATCH `/api/admin/settings`, and a read-only "Boot config" panel from `settings.boot`.

- [ ] **Step 1: Expose flags in context**

In `web/src/store/AppContext.tsx`, surface `sharedPoolEnabled` / `participantsMode` from the `me` payload (grep how `me` is stored today).

- [ ] **Step 2: Conditionally render pool/pledge**

In Dashboard/Profile, wrap the pledge slider + pool widgets in `{sharedPoolEnabled && (...)}`. When `participantsMode === "givers_only" && !me.hasPat`, render the existing PatHelp/onboarding prompt as a blocking call-to-action.

- [ ] **Step 3: Admin toggles**

In `AdminScreen.tsx`, add two controls bound to `settings.participantsMode` and `settings.sharedPoolEnabled`, each calling the existing settings-PATCH path (grep how `AdminScreen` currently PATCHes settings). Add a read-only card rendering `settings.boot` with the note "set in .env — restart to change".

- [ ] **Step 4: Build + verify**

Run: `cd web && npm run build` then `npm run dev`; with mockApi flip the mock `me`/`settings` flags and confirm the UI reacts (pool hidden when off; license prompt when givers_only + no PAT; admin toggles present).

- [ ] **Step 5: Commit**

```bash
git add web/src/store/AppContext.tsx web/src/screens/Dashboard web/src/screens/Profile web/src/screens/Admin
git commit -m "feat(web): mode-aware UI (pool hidden, license gating, admin toggles)"
```

---

## Phase E — Deploy config + docs

### Task 13: Caddyfile transport + `.env.example` + deploy docs

**Files:**
- Modify: `Caddyfile`
- Modify: `.env.example`
- Modify: `docs/guide/07-deploying.md`, `docs/guide/03-identity-and-login.md`
- Modify: `CLAUDE.md` (env var table)

**Interfaces:** none (config + docs).

- [ ] **Step 1: Caddy — serve http when `CTC_WEB_TRANSPORT=http`**

Make the site address scheme-aware. Add to the top of `Caddyfile`:

```caddy
{
	auto_https {$CTC_AUTO_HTTPS:off}
}

{$CTC_WEB_SCHEME:http}://{$CTC_DOMAIN} {
```

…and document that for HTTPS deploys the operator sets `CTC_WEB_SCHEME=https` + `CTC_AUTO_HTTPS=on` (or keeps the explicit `tls /certs/...` block). Keep the existing `tls /certs/cert.pem /certs/key.pem` line inside the block but guarded so http mode does not load it (simplest: two documented site blocks selected by env, or a comment instructing operators which line to keep per mode). Choose the two-block-with-comment approach and document it.

> Implementer note: Caddy cannot conditionally include a directive purely from env. Provide both an `http://` block and an `https://` block in the Caddyfile, each gated by being the active `{$CTC_DOMAIN}` matcher only when its scheme env is set — or, simplest and explicit: ship `Caddyfile` (https, default for prod) and `Caddyfile.http` (plain http), and have `docker-compose.yml` select via `CADDYFILE` path env. Implement the two-file approach; update `docker-compose.yml` to mount the file named by `${CADDYFILE:-Caddyfile}`.

- [ ] **Step 2: `.env.example` — add the four knobs + SMTP + caveats**

Add a documented block:

```bash
# ── Deployment mode (shipped defaults target license-holders-trade-credits) ──
# Auth: email magic-link (no GHE account needed) or ghe_oauth.
CTC_AUTH_MODE=email
# Website transport. http = plain HTTP (NO TLS) — ONLY behind a VPN/trusted LAN,
# because session cookies + magic links travel in plaintext. Must match
# CTC_APP_ORIGIN scheme. For public TLS use https + CADDYFILE=Caddyfile.
CTC_WEB_TRANSPORT=http
# Live admin toggles seed their FIRST-BOOT default from these; afterwards the
# admin panel value wins.
CTC_PARTICIPANTS_MODE=givers_only        # or givers_and_consumers
CTC_SHARED_POOL=off                      # or on

# ── Email (magic-link) ───────────────────────────────────────────────────────
CTC_EMAIL_BACKEND=console                # console logs the link; use smtp in prod
CTC_SMTP_HOST=
CTC_SMTP_PORT=587
CTC_SMTP_USER=
CTC_SMTP_PASS=
CTC_SMTP_FROM=ctc@your-company.com
CTC_SMTP_STARTTLS=1
```

Add a note next to `CTC_ADMINS`: "In email auth mode, list **email addresses** here (matched against the signed-in identity)."

- [ ] **Step 3: Docs — deployment shapes table + upgrade caveat**

In `docs/guide/07-deploying.md` add a "Deployment shapes" table (legacy: ghe_oauth + https + givers_and_consumers + pool on; vs default: email + http + givers_only + pool off) and the upgrade caveat. In `docs/guide/03-identity-and-login.md` document the email magic-link flow. Update the env var table in `CLAUDE.md`.

- [ ] **Step 4: Verify config loads**

Run: `pytest -q` (full suite) — confirm nothing regressed. Manually run `python -c "from ctc.domain.deployment import DeploymentConfig; print(DeploymentConfig.from_env({}))"` and confirm defaults.

- [ ] **Step 5: Commit**

```bash
git add Caddyfile Caddyfile.http docker-compose.yml .env.example docs/guide/07-deploying.md docs/guide/03-identity-and-login.md CLAUDE.md
git commit -m "docs(deploy): mode knobs, SMTP, Caddy http/https, deployment shapes"
```

---

## Phase F — End-to-end smoke (manual, operator-run)

### Task 14: Manual smoke checklist

**Files:** Create `docs/reference/2026-06-23-deployment-modes-smoke.md` (checklist the operator runs).

- [ ] **Step 1: Write the checklist** covering:
  1. **http website**: boot with `CTC_WEB_TRANSPORT=http` + `CTC_APP_ORIGIN=http://…`; load the web app over http, sign in via email magic-link (console backend → copy the logged link), confirm session cookie set without `Secure`.
  2. **givers_only + pool off (defaults)**: a fresh user with no PAT is blocked at the proxy (402 → "add a license"); after adding a PAT they can run Copilot; a second license-holder funds the first's marketplace request and the grant is consumed (`Bucket.GRANT`).
  3. **flip to givers_and_consumers + pool on** in the admin panel; confirm a consumer can now draw from the pool; flip back and confirm immediate block.
  4. **CLI/proxy unchanged**: `ctc login` + a Copilot chat completion still works exactly as before (HTTPS_PROXY + cert), confirming Axis 1 did not touch the proxy.
- [ ] **Step 2: Commit the checklist.**

```bash
git add docs/reference/2026-06-23-deployment-modes-smoke.md
git commit -m "docs: manual smoke checklist for deployment modes"
```

---

## Self-Review notes (for the executor)

- **CLI/proxy untouched:** no task modifies `proxy.py` request handling or the `cli/ctc` proxy envvars. If a task tempts you to, stop — Axis 1 is website-only.
- **Pool-off ⇒ no auto-pledge** is achieved purely by `EffectiveConfig.default_pledge_pct` returning 0 (Task 2); `ctc/auth/onboarding.py` already reads that value and skips the pledge when 0 — do not add a second gate there.
- **Legacy tests:** Tasks 8/10 change `make_app`/`register_admin_routes` signatures. Update existing call sites in `tests/` and `api_server.build_from_env` in the same commit so the suite stays green.
- **Email identity** is stored in `users.ghe_login`; admin allowlist matching is unchanged (it lowercases and compares), so emails "just work" as admin identifiers.
