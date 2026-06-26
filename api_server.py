from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from aiohttp import web

from ctc.store.db import connect, init_db
from ctc.store.auth_store import AuthStore
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.auth.crypto import derive_key
from ctc.auth.registry import AuthRegistry
from ctc.auth.sessions import SessionService
from ctc.auth.oauth import GheOAuth, AiohttpJson
from ctc.auth.onboarding import validate_and_store_pat, PatInvalid, PatIdentityMismatch
from ctc.auth.admin import is_admin as _is_admin
from ctc.domain.deployment import DeploymentConfig

COOKIE = "ctc_session"
STATE_COOKIE = "ctc_oauth_state"


def assert_transport_consistent(deployment, app_origin) -> None:
    origin_https = app_origin.startswith("https")
    if (deployment.web_transport == "https") != origin_https:
        raise ValueError(
            f"CTC_WEB_TRANSPORT={deployment.web_transport} but CTC_APP_ORIGIN="
            f"{app_origin!r}; scheme must match")


def _sign(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def make_app(*, store, engine, registry, sessions, oauth=None, http_get_user,
             cycle_id=None, secret, app_origin, admins=frozenset(),
             ca_cert_path="/certs/cert.pem",
             deployment: DeploymentConfig, magic_link=None,
             now=lambda: int(time.time())):

    from ctc.auth.ca_fingerprint import ca_fingerprint_sha256
    _ca_fingerprint = ca_fingerprint_sha256(ca_cert_path)

    # ── CORS middleware ──────────────────────────────────────────────────────
    @web.middleware
    async def cors_middleware(req, handler):
        resp = await handler(req)
        resp.headers["Access-Control-Allow-Origin"] = app_origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Headers"] = "content-type"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,DELETE,OPTIONS"
        return resp

    # ── JSON-error middleware ────────────────────────────────────────────────
    @web.middleware
    async def json_error_middleware(req, handler):
        # Answer OPTIONS preflight before routing (no route registered for OPTIONS)
        if req.method == "OPTIONS":
            resp = web.Response(status=204)
            resp.headers["Access-Control-Allow-Origin"] = app_origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Headers"] = "content-type"
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,DELETE,OPTIONS"
            return resp
        try:
            resp = await handler(req)
            return resp
        except web.HTTPException as exc:
            if exc.status >= 400:
                # Derive a stable short error code from the HTTP reason phrase
                error_code = exc.reason.lower().replace(" ", "_") if exc.reason else "error"
                return web.json_response(
                    {"error": error_code, "message": exc.text or exc.reason},
                    status=exc.status,
                )
            raise

    # cors_middleware must be outermost so it applies to responses synthesized
    # by json_error_middleware (which catches HTTPExceptions before they propagate).
    app = web.Application(middlewares=[cors_middleware, json_error_middleware])

    async def current_user(req):
        cookie = req.cookies.get(COOKIE)
        uid = sessions.user_id_for(cookie, now()) if cookie else None
        return store.get_user_by_id(uid) if uid else None

    def admin_only(handler):
        async def wrapped(req):
            user = await current_user(req)
            if not user:
                raise web.HTTPUnauthorized(text="no session")
            if not _is_admin(user["ghe_login"], admins):
                raise web.HTTPForbidden(text="admin only")
            return await handler(req, user)
        return wrapped

    async def auth_login(req):
        state = uuid.uuid4().hex
        resp = web.HTTPFound(oauth.authorize_url(state))
        secure = app_origin.startswith("https")
        resp.set_cookie(STATE_COOKIE, f"{state}.{_sign(secret, state)}",
                        httponly=True, samesite="Lax", max_age=600, secure=secure)
        raise resp

    async def auth_callback(req):
        code = req.query.get("code", "")
        state = req.query.get("state", "")
        cookie = req.cookies.get(STATE_COOKIE, "")
        cstate, _, csig = cookie.partition(".")
        if not state or state != cstate or not hmac.compare_digest(_sign(secret, state), csig):
            raise web.HTTPBadRequest(text="bad oauth state")
        token = await oauth.exchange_code(code)
        ident = await oauth.fetch_identity(token)
        user = store.get_user_by_login(ident["login"])
        if user is None:
            uid = uuid.uuid4().hex
            store.upsert_user(uid, ident["login"], ident["name"], "consumer", now())
            user = store.get_user_by_id(uid)
        cookie_val = sessions.create(user["id"], now())
        secure = app_origin.startswith("https")
        resp = web.HTTPFound(app_origin)
        resp.set_cookie(COOKIE, cookie_val, httponly=True, samesite="Lax", secure=secure)
        resp.del_cookie(STATE_COOKIE)
        raise resp

    async def auth_logout(req):
        cookie = req.cookies.get(COOKIE)
        if cookie:
            sessions.revoke(cookie)
        resp = web.Response(status=204)
        resp.del_cookie(COOKIE)
        return resp

    from ctc.store.settings_store import SettingsStore
    from ctc.domain.settings import EffectiveConfig
    _settings_store = SettingsStore(store.conn)
    _ec = getattr(engine, "config", None)
    _effective_config = _ec if isinstance(_ec, EffectiveConfig) else EffectiveConfig(_settings_store)

    async def api_me(req):
        user = await current_user(req)
        if not user:
            raise web.HTTPUnauthorized(text="no session")
        return web.json_response({
            "user_id": user["id"], "ghe_login": user["ghe_login"],
            "display_name": user["display_name"], "role": user["role"],
            "has_pat": store.get_giver_pat(user["id"]) is not None,
            "onboarded": bool(user["onboarded"]),
            "is_admin": _is_admin(user["ghe_login"], admins),
            "auth_mode": deployment.auth_mode,
            "web_transport": deployment.web_transport,
            "participants_mode": _effective_config.participants_mode,
            "shared_pool_enabled": _effective_config.shared_pool_enabled,
        })

    async def api_pat(req):
        user = await current_user(req)
        if not user:
            raise web.HTTPUnauthorized(text="no session")
        # Resolve cycle per-request so it reflects the live DB state
        cycle = engine.current_cycle()
        if cycle is None:
            raise web.HTTPServiceUnavailable(text="no active cycle")
        live_cycle_id = cycle.id
        body = await req.json()
        pat = (body or {}).get("pat", "")
        if not pat:
            raise web.HTTPBadRequest(text="pat required")
        try:
            res = await validate_and_store_pat(registry, engine, http_get_user,
                                               live_cycle_id, user["id"], user["ghe_login"], pat,
                                               now(), effective_config=getattr(engine, "config", None),
                                               enforce_identity=(deployment.auth_mode == "ghe_oauth"))
        except PatIdentityMismatch as e:
            raise web.HTTPConflict(text=str(e))
        except PatInvalid as e:
            raise web.HTTPBadRequest(text=str(e))
        return web.json_response(res)

    async def api_token_create(req):
        user = await current_user(req)
        if not user:
            raise web.HTTPUnauthorized(text="no session")
        tid, token, fp = registry.issue_proxy_token(user["id"], now())
        return web.json_response({"id": tid, "token": token, "fingerprint": fp,
                                  "ca_fingerprint": _ca_fingerprint})

    async def api_token_list(req):
        user = await current_user(req)
        if not user:
            raise web.HTTPUnauthorized(text="no session")
        rows = store.list_proxy_tokens(user["id"])
        return web.json_response([
            {"id": r["id"], "fingerprint": r["fingerprint"],
             "created_at": r["created_at"], "revoked": r["revoked_at"] is not None}
            for r in rows
        ])

    async def api_token_delete(req):
        user = await current_user(req)
        if not user:
            raise web.HTTPUnauthorized(text="no session")
        registry.store.revoke_proxy_token(req.match_info["id"], user["id"], now())
        return web.Response(status=204)

    async def api_onboarding_complete(req):
        user = await current_user(req)
        if not user:
            raise web.HTTPUnauthorized(text="no session")
        store.set_onboarded(user["id"])
        return web.Response(status=204)

    _quota_cache = {}  # giver_id -> (fetched_at, value|None)

    async def live_quota(giver_id):
        hit = _quota_cache.get(giver_id)
        # Serve a fresh, non-None cache hit; always retry when the last fetch failed.
        if hit and hit[1] is not None and now() - hit[0] < 60:
            return hit[1]
        pat = registry.pat_for(giver_id)
        value = None
        if pat:
            try:
                u = await http_get_user(pat)
                pi = u.get("quota_snapshots", {}).get("premium_interactions", {})
                value = {"entitlement": pi.get("entitlement"),
                         "remaining": pi.get("remaining"),
                         "reset_date": u.get("quota_reset_date")}
            except Exception:
                value = None
        _quota_cache[giver_id] = (now(), value)
        return value

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

    from ctc.api.web_routes import register_web_routes
    register_web_routes(app, store=store, engine=engine, current_user=current_user,
                        now=now, live_quota=live_quota)

    from ctc.api.admin_routes import register_admin_routes
    register_admin_routes(app, store=store, engine=engine, registry=registry,
                          settings_store=_settings_store, effective_config=_effective_config,
                          admin_only=admin_only, now=now, deployment=deployment)

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

    app.add_routes([
        web.get("/api/config", api_config),
        web.post("/auth/logout", auth_logout),
        web.get("/api/me", api_me),
        web.post("/api/pat", api_pat),
        web.post("/api/proxy-token", api_token_create),
        web.get("/api/proxy-token", api_token_list),
        web.delete("/api/proxy-token/{id}", api_token_delete),
        web.post("/api/onboarding/complete", api_onboarding_complete),
    ])
    return app


def build_from_env(session) -> web.Application:
    """Build the app from env, using a caller-supplied aiohttp session (created
    inside the event loop — aiohttp forbids ClientSession() with no running loop)."""
    secret = os.environ["CTC_SECRET_KEY"]
    conn = connect(os.environ["CTC_DB_PATH"])
    init_db(conn)
    store = AuthStore(conn)
    from ctc.store.settings_store import SettingsStore
    from ctc.domain.settings import EffectiveConfig
    settings_store = SettingsStore(conn)
    effective_config = EffectiveConfig(settings_store)
    engine = AccountingEngine(AccountingStore(conn), config=effective_config)
    # Never let a fresh/empty DB block the app on "no active cycle" — open the
    # current month's cycle on startup if none is active (idempotent).
    engine.ensure_active_cycle(int(time.time()))
    registry = AuthRegistry(store, derive_key(secret))
    sessions = SessionService(store, secret=secret)

    deployment = DeploymentConfig.from_env(os.environ)
    app_origin = os.environ.get("CTC_APP_ORIGIN", "/")
    assert_transport_consistent(deployment, app_origin)

    # api_base is required in both modes (PAT onboarding calls /copilot_internal/user).
    # GHE_OAUTH_BASE and GHE_OAUTH_* are only required in ghe_oauth mode.
    api_base = os.environ["GHE_API_BASE"].rstrip("/")

    async def http_get_user(pat):
        headers = {"authorization": f"Bearer {pat}", "editor-version": "copilot/1.0.63",
                   "copilot-integration-id": "copilot-developer-cli"}
        async with session.get(f"{api_base}/copilot_internal/user", headers=headers) as r:
            if r.status != 200:
                raise PatInvalid(f"/copilot_internal/user -> {r.status}")
            return await r.json()

    oauth = None
    magic_link = None
    if deployment.auth_mode == "ghe_oauth":
        base = os.environ["GHE_OAUTH_BASE"].rstrip("/")
        oauth = GheOAuth(os.environ["GHE_OAUTH_CLIENT_ID"], os.environ["GHE_OAUTH_CLIENT_SECRET"],
                         os.environ["GHE_OAUTH_REDIRECT_URI"], base, http=AiohttpJson(session))
    else:
        from ctc.auth.email_sender import email_sender_from_env
        from ctc.auth.magic_link import EmailMagicLink
        sender = email_sender_from_env(os.environ, logging.getLogger("ctc.email"))
        magic_link = EmailMagicLink(store, secret, app_origin, sender)

    from ctc.auth.admin import admins_from_env
    admins = admins_from_env(os.environ)
    ca_cert_path = os.environ.get("CTC_CA_CERT", "/certs/cert.pem")
    return make_app(store=store, engine=engine, registry=registry, sessions=sessions,
                    oauth=oauth, http_get_user=http_get_user,
                    secret=secret, app_origin=app_origin,
                    admins=admins, ca_cert_path=ca_cert_path,
                    deployment=deployment, magic_link=magic_link)


async def _serve() -> None:
    import aiohttp
    # Configure logging so INFO-level records surface in container stdout — without
    # this, the console email backend logs the magic-link at INFO and Python's
    # default WARNING threshold silently drops it (login becomes impossible).
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    port = int(os.environ.get("CONTROL_PLANE_PORT", "8090"))
    async with aiohttp.ClientSession() as session:  # created inside the running loop
        app = build_from_env(session)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"control-plane listening on :{port}", flush=True)
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(_serve())
