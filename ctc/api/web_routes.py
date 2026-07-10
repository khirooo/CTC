from __future__ import annotations

from aiohttp import web

from ..accounting.errors import InsufficientCredit, InvalidConsumption, InvalidPledge, RequestClosed
from ..accounting.leaderboard import LeaderboardUser, build_leaderboard, giver_tier_inputs
from ..accounting.reports import build_dashboard, build_history
from ..accounting.tiers import assign_tiers
from ..auth.pat_health import display_status
from ..domain.config import NANO_PER_AIU
from ..domain.types import Role
from .serializers import (CreateRequestDTO, DonateDTO, ListRequestsDTO, OwnProfileDTO,
                          PublicProfileDTO, PublicRequestDTO, PublicUserDTO, PublicUserHitDTO,
                          RoleCountsDTO, SettingsDTO, SettingsPatchDTO, build_public_request,
                          initials)


def register_web_routes(app, *, store, engine, current_user, now, live_quota):
    # store = AuthStore (get_user_by_id); engine.store = AccountingStore (list_requests, etc.)
    get_user = store.get_user_by_id
    acct = engine.store

    async def _require_user(req):
        user = await current_user(req)
        if not user:
            raise web.HTTPUnauthorized(text="no session")
        return user

    def _cycle():
        # ensure_active_cycle also rolls a month-ended cycle over to the new month
        # (archive + open + seed) on first access — see AccountingEngine.
        c = engine.ensure_active_cycle(now())
        if c is None:
            raise web.HTTPServiceUnavailable(text="no active cycle")
        return c

    async def list_requests(req):
        user = await _require_user(req)
        cycle = _cycle()
        ts = now()
        dtos = [build_public_request(acct, get_user, r, ts, viewer_id=user["id"])
                for r in acct.list_requests(cycle.id)]
        counts = RoleCountsDTO(
            all=len(dtos),
            pro=sum(1 for d in dtos if d.requester_role == "pro"),
            noob=sum(1 for d in dtos if d.requester_role == "noob"),
        )
        f = req.query.get("filter", "all")
        if f in ("pro", "noob"):
            dtos = [d for d in dtos if d.requester_role == f]
        pool_enabled = bool(getattr(engine.config, "shared_pool_enabled", True))
        pool_available = engine.pool_available(cycle.id) if pool_enabled else 0
        return web.json_response(ListRequestsDTO(
            requests=dtos, counts=counts,
            pool_enabled=pool_enabled, pool_available=pool_available,
        ).model_dump(by_alias=True))

    async def create_request(req):
        user = await _require_user(req)
        body = CreateRequestDTO.model_validate(await req.json())
        cycle = _cycle()
        ts = now()
        # Timestamps are SECONDS across the unified server (auth/sessions/proxy
        # all use int(time.time())); keep request times in the same unit.
        hours = body.expiry_hours if body.expiry_hours is not None else engine.config.request_expiry_hours
        if not (1 <= hours <= engine.config.request_expiry_max_hours):
            raise web.HTTPUnprocessableEntity(
                text=f"expiry_hours must be between 1 and {engine.config.request_expiry_max_hours}")
        expires = min(ts + hours * 3600, cycle.ends_at)
        role = Role(user["role"])
        r = engine.create_request(cycle.id, user["id"], role, body.amount_needed,
                                  body.reason, body.target, ts, expires)
        return web.json_response(build_public_request(acct, get_user, r, ts, viewer_id=user["id"]).model_dump(by_alias=True))

    async def donate(req):
        user = await _require_user(req)
        body = DonateDTO.model_validate(await req.json())
        rid = req.match_info["id"]
        if acct.get_request(rid) is None:
            raise web.HTTPNotFound(text="request not found")
        ts = now()
        try:
            engine.fund_request(rid, user["id"], body.amount, ts)
        except RequestClosed as e:
            raise web.HTTPConflict(text=str(e))
        except (InsufficientCredit, InvalidConsumption) as e:
            raise web.HTTPUnprocessableEntity(text=str(e))
        return web.json_response(build_public_request(acct, get_user, acct.get_request(rid), ts).model_dump(by_alias=True))

    async def pool_fund(req):
        user = await _require_user(req)
        body = DonateDTO.model_validate(await req.json())
        rid = req.match_info["id"]
        if acct.get_request(rid) is None:
            raise web.HTTPNotFound(text="request not found")
        if not getattr(engine.config, "shared_pool_enabled", True):
            raise web.HTTPConflict(text="the shared pool is disabled")
        ts = now()
        try:
            engine.fund_request_from_pool(rid, user["id"], body.amount, ts)
        except RequestClosed as e:
            raise web.HTTPConflict(text=str(e))
        except (InsufficientCredit, InvalidConsumption) as e:
            raise web.HTTPUnprocessableEntity(text=str(e))
        return web.json_response(build_public_request(
            acct, get_user, acct.get_request(rid), ts, viewer_id=user["id"]).model_dump(by_alias=True))

    async def delete_request(req):
        user = await _require_user(req)
        rid = req.match_info["id"]
        r = acct.get_request(rid)
        if r is None:
            raise web.HTTPNotFound(text="request not found")
        if r.requester_id != user["id"]:
            raise web.HTTPForbidden(text="only the requester can delete their request")
        try:
            engine.cancel_request(rid, user["id"], now())
        except RequestClosed as e:
            raise web.HTTPConflict(text=str(e))
        return web.Response(status=204)

    def _settings_for(user, cycle_id):
        gc = engine.store.get_giver_cycle(cycle_id, user["id"])
        quota = gc.quota if gc else 0
        pledge = gc.pledge if gc else 0
        role = user["role"]
        health = store.get_pat_health(user["id"])
        return SettingsDTO(
            name=user["display_name"], login=user["ghe_login"], role=role,
            has_pat=store.get_giver_pat(user["id"]) is not None,
            pat_health=display_status(health),
            pat_health_checked_at=health["checked_at"] if health else None,
            total_credit=quota if quota else None,
            pledged_surplus=pledge,
        )

    async def get_settings(req):
        user = await _require_user(req)
        cycle = _cycle()
        return web.json_response(_settings_for(user, cycle.id).model_dump(by_alias=True))

    async def patch_settings(req):
        user = await _require_user(req)
        cycle = _cycle()
        body = SettingsPatchDTO.model_validate(await req.json())
        if body.pledged_surplus is not None and user["role"] == "giver":
            # Pledging is a pool-only concept; with the shared pool off it is
            # locked at 0. Reject any attempt to set a pledge (defense in depth:
            # the UI already hides the slider when the pool is off).
            if not getattr(engine.config, "shared_pool_enabled", True) \
                    and body.pledged_surplus != 0:
                raise web.HTTPUnprocessableEntity(
                    text="pledging is disabled while the shared pool is off")
            try:
                engine.set_pledge(cycle.id, user["id"], body.pledged_surplus)
            except InvalidPledge as e:
                raise web.HTTPUnprocessableEntity(text=str(e))
        return web.json_response(_settings_for(user, cycle.id).model_dump(by_alias=True))

    # --- read endpoints (dashboard / leaderboard / history / profile) ---
    # The accounting builders return wire-ready dicts (camelCase keys, RAW
    # nano-AIU values — the frontend `aiu()` helper divides by NANO_PER_AIU for
    # display), so they are serialized straight through. Nano is the wire unit
    # for ALL endpoints; the frontend converts AIU<->nano only at the edge.
    def _leaderboard_users():
        return [LeaderboardUser(u["id"], u["display_name"] or u["ghe_login"], u["role"] == "giver")
                for u in store.list_users()]

    async def get_leaderboard(req):
        await _require_user(req)
        cycle = _cycle()
        return web.json_response(build_leaderboard(engine, _leaderboard_users(), cycle.id))

    async def get_dashboard(req):
        await _require_user(req)
        cycle = _cycle()
        return web.json_response(build_dashboard(engine, _leaderboard_users(), cycle.id, now()))

    async def get_history(req):
        await _require_user(req)
        return web.json_response(build_history(engine, _leaderboard_users(), now()))

    def _iso_date(ts: int) -> str:
        import datetime
        # Clamp pathological timestamps to year 3000 to avoid platform fromtimestamp
        # overflow; realistic cycle ends pass through unchanged.
        max_ts = 32503680000  # 3000-01-01 UTC
        safe_ts = min(ts, max_ts)
        return datetime.datetime.fromtimestamp(safe_ts, datetime.timezone.utc).strftime("%Y-%m-%d")

    async def get_profile(req):
        user = await _require_user(req)
        cycle = _cycle()
        uid = user["id"]
        name = user["display_name"] or user["ghe_login"]
        gc = acct.get_giver_cycle(cycle.id, uid)
        is_giver = user["role"] == "giver" and gc is not None
        recv_grants = acct.grants_for_recipient(cycle.id, uid)
        # How much of the received credit the recipient has actually burned vs.
        # still has to draw (the profile "routed to you" bar splits on this).
        # A grant on a cancelled request only counts for the part already burned —
        # the unconsumed remainder went back to its donor.
        donations_received = 0
        donations_received_remaining = 0
        donations_received_from_pool = 0
        for g in recv_grants:
            rq = acct.get_request(g.request_id)
            cancelled = rq is not None and rq.cancelled_at is not None
            amt = acct.grant_consumed(cycle.id, g.id) if cancelled else g.amount
            donations_received += amt
            donations_received_remaining += engine.grant_remaining(cycle.id, g.id)
            if g.source == "pool":
                donations_received_from_pool += amt
        donations_received_consumed = max(0, donations_received - donations_received_remaining)

        common = dict(
            user=PublicUserDTO(id=uid, name=name, initials=initials(name), role=user["role"]),
            donated_so_far=engine.donated_live(cycle.id, uid),
            consumed=engine.consumed_total(cycle.id, uid),
            donations_received=donations_received,
            donations_received_consumed=donations_received_consumed,
            donations_received_remaining=donations_received_remaining,
            donations_received_from_pool=donations_received_from_pool,
        )

        # Aristocracy tier (givers-only) — computed over all givers this cycle so
        # the profile badge matches the leaderboard standings exactly.
        tier = net = net_to_next = None
        if is_giver:
            ranked = assign_tiers(giver_tier_inputs(engine, _leaderboard_users(), cycle.id))
            for idx, r in enumerate(ranked):
                if r.user_id == uid:
                    tier, net = r.tier, r.net
                    if idx > 0 and r.tier != "newcomer":
                        net_to_next = max(1, ranked[idx - 1].net - r.net)
                    break
        common["tier"] = tier
        common["net"] = net
        common["net_to_next"] = net_to_next

        if not is_giver:
            dto = OwnProfileDTO(
                total_credit=None, pledged_surplus=None, retained=None,
                reset_date=_iso_date(cycle.ends_at), **common)
            return web.json_response(dto.model_dump(by_alias=True))

        # giver: live reconcile (fallback to submit-time snapshot)
        lq = await live_quota(uid)
        stale = False
        if lq and lq.get("entitlement") is not None:
            ent_aiu, rem_aiu, reset = lq["entitlement"], lq["remaining"], lq["reset_date"]
        else:
            snap = store.get_giver_quota_snapshot(uid)
            stale = True
            ent_aiu = snap["entitlement"] if snap else 0
            rem_aiu = snap["remaining_at_submit"] if snap else 0
            reset = snap["quota_reset_date"] if snap else None

        # Trigger T1: reconcile out-of-band burn into events before reading usage,
        # so profile, leaderboard and dashboard all derive the same number. No-op
        # when stale (lq is None / entitlement None) or unlimited.
        if lq and lq.get("entitlement") is not None:
            engine.reconcile_giver(cycle.id, uid, lq)

        unlimited = ent_aiu == -1
        pledged = gc.pledge
        donated = acct.granted_out(cycle.id, uid)
        # Pledge usage counts legacy pool events plus marketplace pool fills;
        # personal chip-in usage counts personal grants only.
        pledged_consumed = engine.pledge_used(cycle.id, uid)
        donated_consumed = acct.personal_grants_consumed_from(cycle.id, uid)
        donated_remaining = max(0, donated - donated_consumed)
        pledged_remaining = engine.pledge_remaining(cycle.id, uid)
        if unlimited:
            dto = OwnProfileDTO(
                total_credit=gc.quota, pledged_surplus=pledged,
                retained=engine.personal_remaining(cycle.id, uid),
                entitlement=-1, remaining=None, unlimited=True, quota_stale=stale,
                pledged=pledged, donated=donated, used=None, left=None,
                pledged_consumed=pledged_consumed, donated_consumed=donated_consumed,
                donated_remaining=donated_remaining, pledged_remaining=pledged_remaining,
                reset_date=reset, **common)
            return web.json_response(dto.model_dump(by_alias=True))

        E = int(ent_aiu) * NANO_PER_AIU
        R = int(rem_aiu or 0) * NANO_PER_AIU
        used = acct.own_consumed(cycle.id, uid) + acct.bypass_consumed(cycle.id, uid)
        left = max(0, E - used - pledged - donated)
        dto = OwnProfileDTO(
            total_credit=gc.quota, pledged_surplus=pledged,
            retained=engine.personal_remaining(cycle.id, uid),
            entitlement=E, remaining=R, used=used, pledged=pledged, donated=donated, left=left,
            pledged_consumed=pledged_consumed, donated_consumed=donated_consumed,
            donated_remaining=donated_remaining, pledged_remaining=pledged_remaining,
            reset_date=reset, unlimited=False, quota_stale=stale, **common)
        return web.json_response(dto.model_dump(by_alias=True))

    async def search_users(req):
        await _require_user(req)
        q = (req.query.get("q") or "").strip()
        if not q:
            return web.json_response({"users": []})
        hits = store.search_users(q, 8)
        users = [
            PublicUserHitDTO(
                id=u["id"], login=u["ghe_login"],
                name=u["display_name"] or u["ghe_login"],
                initials=initials(u["display_name"] or u["ghe_login"]),
                role=u["role"],
            ).model_dump(by_alias=True)
            for u in hits
        ]
        return web.json_response({"users": users})

    async def get_public_user(req):
        await _require_user(req)
        uid = req.match_info["id"]
        u = store.get_user_by_id(uid)
        if u is None:
            return web.json_response({"error": "not found"}, status=404)
        cycle = _cycle()
        name = u["display_name"] or u["ghe_login"]
        tier = net = donated = donations_made = None
        if u["role"] == "giver":
            ranked = assign_tiers(giver_tier_inputs(engine, _leaderboard_users(), cycle.id))
            entry = next((r for r in ranked if r.user_id == uid), None)
            tier = entry.tier if entry else None
            net = entry.net if entry else None
            donated = engine.donated_live(cycle.id, uid)
            donations_made = acct.grants_count_by(cycle.id, uid)
        dto = PublicProfileDTO(
            id=uid, name=name, login=u["ghe_login"], initials=initials(name),
            role=u["role"], tier=tier, net=net, donated=donated,
            donations_made=donations_made,
        )
        return web.json_response(dto.model_dump(by_alias=True))

    app.add_routes([
        web.get("/api/users/search", search_users),
        web.get("/api/users/{id}", get_public_user),
        web.get("/api/requests", list_requests),
        web.post("/api/requests", create_request),
        web.post("/api/requests/{id}/donate", donate),
        web.post("/api/requests/{id}/pool-fund", pool_fund),
        web.delete("/api/requests/{id}", delete_request),
        web.get("/api/settings", get_settings),
        web.patch("/api/settings", patch_settings),
        web.get("/api/leaderboard", get_leaderboard),
        web.get("/api/dashboard", get_dashboard),
        web.get("/api/history", get_history),
        web.get("/api/profile", get_profile),
    ])
