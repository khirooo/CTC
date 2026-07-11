from __future__ import annotations

import uuid
from aiohttp import web

from ..auth.pat_health import display_status
from ..domain.settings import effective_view, validate_patch


def register_admin_routes(app, *, store, engine, registry, settings_store,
                          effective_config, admin_only, now, deployment):
    acct = engine.store

    def _balances(user_id, role):
        """Giver balances from the active cycle, or (None, None, None)."""
        if role != "giver":
            return None, None, None
        cycle = engine.ensure_active_cycle(now())
        if cycle is None:
            return None, None, None
        gc = acct.get_giver_cycle(cycle.id, user_id)
        if gc is None:
            return None, None, None
        return gc.quota, gc.pledge, engine.pledge_remaining(cycle.id, user_id)

    @admin_only
    async def list_users(req, _admin):
        out = []
        for u in store.list_users_admin():
            quota, pledge, pledge_rem = _balances(u["id"], u["role"])
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
                "quota": quota, "pledge": pledge, "pledge_remaining": pledge_rem,
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
        quota, pledge, pledge_rem = _balances(uid, u["role"])
        return web.json_response({
            "id": u["id"], "ghe_login": u["ghe_login"], "display_name": u["display_name"],
            "role": u["role"], "onboarded": bool(u["onboarded"]),
            "pat_health": display_status(health),
            "pat_health_checked_at": health["checked_at"] if health else None,
            "pat_health_error": health["error"] if health else None,
            "proxy_tokens": tokens, "pat": pat,
            "quota": quota, "pledge": pledge, "pledge_remaining": pledge_rem,
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
        web.get("/api/admin/settings", get_settings),
        web.patch("/api/admin/settings", patch_settings),
    ])
