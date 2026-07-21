from __future__ import annotations

import uuid
from aiohttp import web

from ..accounting.errors import AccountingError
from ..auth.pat_health import display_status
from ..domain.settings import effective_view, validate_patch


def register_admin_routes(app, *, store, engine, registry, settings_store,
                          effective_config, admin_only, now, deployment):
    acct = engine.store

    _NO_BAL = {"quota": None, "pledge": None, "pledge_remaining": None,
               "used": None, "donated": None}

    def _balances(user_id, role):
        """Giver balances from the active cycle, or all-None for non-givers.

        `used`/`donated` let the admin pledge control size its percentage
        presets against the true shareable slice (quota - used - donated),
        exactly like the Profile slider."""
        if role != "giver":
            return dict(_NO_BAL)
        cycle = engine.ensure_active_cycle(now())
        if cycle is None:
            return dict(_NO_BAL)
        gc = acct.get_giver_cycle(cycle.id, user_id)
        if gc is None:
            return dict(_NO_BAL)
        used = acct.own_consumed(cycle.id, user_id) + acct.bypass_consumed(cycle.id, user_id)
        return {
            "quota": gc.quota, "pledge": gc.pledge,
            "pledge_remaining": engine.pledge_remaining(cycle.id, user_id),
            "used": used, "donated": acct.granted_out(cycle.id, user_id),
        }

    @admin_only
    async def list_users(req, _admin):
        out = []
        for u in store.list_users_admin():
            bal = _balances(u["id"], u["role"])
            out.append({
                "id": u["id"], "ghe_login": u["ghe_login"],
                "display_name": u["display_name"], "role": u["role"],
                "onboarded": bool(u["onboarded"]),
                "has_pat": u["pat_fingerprint"] is not None,
                "pat_fingerprint": u["pat_fingerprint"],
                "pat_health": display_status(
                    {"status": u["pat_health_status"], "error": u["pat_health_error"]}
                    if u["pat_fingerprint"] is not None else None),
                "pat_health_checked_at": u["pat_health_checked_at"],
                "pat_health_error": u["pat_health_error"],
                "token_count": u["token_count"],
                **bal,
            })
        return web.json_response(out)

    @admin_only
    async def user_detail(req, _admin):
        uid = req.match_info["id"]
        u = store.get_user_by_id(uid)
        if u is None:
            raise web.HTTPNotFound(text="unknown user")
        tokens = [{"id": t["id"], "fingerprint": t["fingerprint"],
                   "created_at": t["created_at"], "revoked": t["revoked_at"] is not None}
                  for t in store.list_proxy_tokens(uid)]
        pat_row = store.get_giver_pat(uid)
        pat = ({"fingerprint": pat_row["fingerprint"], "created_at": pat_row["created_at"]}
               if pat_row else None)
        health = store.get_pat_health(uid)
        bal = _balances(uid, u["role"])
        return web.json_response({
            "id": u["id"], "ghe_login": u["ghe_login"], "display_name": u["display_name"],
            "role": u["role"], "onboarded": bool(u["onboarded"]),
            "pat_health": display_status(health),
            "pat_health_checked_at": health["checked_at"] if health else None,
            "pat_health_error": health["error"] if health else None,
            "proxy_tokens": tokens, "pat": pat,
            **bal,
        })

    @admin_only
    async def reveal_pat(req, admin):
        # The PAT is returned in cleartext over the wire; require TLS transport so
        # it can't be sniffed on a plain-HTTP (VPN/LAN) deployment.
        if deployment.web_transport != "https":
            raise web.HTTPForbidden(text="reveal-pat requires https transport")
        uid = req.match_info["id"]
        pat = registry.pat_for(uid)
        if pat is None:
            raise web.HTTPNotFound(text="no pat on file")
        store.add_admin_audit(uuid.uuid4().hex, admin["id"], admin["ghe_login"],
                              "reveal_pat", uid, now())
        return web.json_response({"pat": pat})

    @admin_only
    async def set_pledge(req, admin):
        # Route an idle giver's remaining credit into the shared pool on their
        # behalf. Same primitive as the user's own pledge slider
        # (engine.set_pledge), just admin-initiated for another user, with an
        # audit row so it's traceable who moved the credit.
        if not getattr(engine.config, "shared_pool_enabled", True):
            raise web.HTTPConflict(text="the shared pool is disabled")
        uid = req.match_info["id"]
        u = store.get_user_by_id(uid)
        if u is None:
            raise web.HTTPNotFound(text="unknown user")
        if u["role"] != "giver":
            raise web.HTTPConflict(text="user is not a giver (no credit to route)")
        cycle = engine.ensure_active_cycle(now())
        if cycle is None:
            raise web.HTTPServiceUnavailable(text="no active cycle")
        if acct.get_giver_cycle(cycle.id, uid) is None:
            raise web.HTTPConflict(text="user has no credit this cycle")
        body = await req.json()
        pledge = body.get("pledge") if isinstance(body, dict) else None
        if not isinstance(pledge, int) or isinstance(pledge, bool):
            raise web.HTTPBadRequest(text="pledge (integer nano-AIU) required")
        try:
            engine.set_pledge(cycle.id, uid, pledge)
        except AccountingError as e:
            raise web.HTTPUnprocessableEntity(text=str(e))
        store.add_admin_audit(uuid.uuid4().hex, admin["id"], admin["ghe_login"],
                              "set_pledge", uid, now())
        return web.json_response(_balances(uid, u["role"]))

    @admin_only
    async def get_settings(req, _admin):
        view = effective_view(effective_config, settings_store)
        view["boot"] = {"web_transport": deployment.web_transport,
                        "source": "env"}
        return web.json_response(view)

    @admin_only
    async def patch_settings(req, admin):
        body = await req.json()
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="body must be a JSON object")
        current = {
            "request_expiry_hours": effective_config.request_expiry_hours,
            "request_expiry_max_hours": effective_config.request_expiry_max_hours,
        }
        try:
            items = validate_patch(body or {}, current=current)
        except ValueError as e:
            raise web.HTTPBadRequest(text=str(e))
        settings_store.set_many(items, admin["ghe_login"], now())
        return web.json_response(effective_view(effective_config, settings_store))

    app.add_routes([
        web.get("/api/admin/users", list_users),
        web.get("/api/admin/users/{id}", user_detail),
        web.post("/api/admin/users/{id}/reveal-pat", reveal_pat),
        web.post("/api/admin/users/{id}/pledge", set_pledge),
        web.get("/api/admin/settings", get_settings),
        web.patch("/api/admin/settings", patch_settings),
    ])
