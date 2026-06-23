from __future__ import annotations

import uuid
from aiohttp import web

from ..domain.settings import effective_view, validate_patch


def register_admin_routes(app, *, store, engine, registry, settings_store,
                          effective_config, admin_only, now, deployment):
    acct = engine.store

    def _balances(user_id, role):
        """Giver balances from the active cycle, or (None, None, None)."""
        if role != "giver":
            return None, None, None
        cycle = engine.current_cycle()
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
        quota, pledge, pledge_rem = _balances(uid, u["role"])
        return web.json_response({
            "id": u["id"], "ghe_login": u["ghe_login"], "display_name": u["display_name"],
            "role": u["role"], "onboarded": bool(u["onboarded"]),
            "proxy_tokens": tokens, "pat": pat,
            "quota": quota, "pledge": pledge, "pledge_remaining": pledge_rem,
        })

    @admin_only
    async def reveal_pat(req, admin):
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
        view["boot"] = {"auth_mode": deployment.auth_mode,
                        "web_transport": deployment.web_transport,
                        "email_backend": deployment.email_backend,
                        "source": "env"}
        return web.json_response(view)

    @admin_only
    async def patch_settings(req, admin):
        body = await req.json()
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
