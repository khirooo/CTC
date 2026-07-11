from __future__ import annotations

import sqlite3

from ..domain.types import Bucket, Cycle, Event, Grant, GiverCycle, PoolContribution, Request, Role

# Cancelled-aware "charge" of a leaf grant `c` (one with no children of its own —
# re-donation depth is capped at 1): while its request is live it charges its
# funder in full; once cancelled, only what the recipient already burned stays
# charged. Expects `rc` = c's request row and `uc` = grant-bucket usage subquery.
_LEAF_CHARGE = ("CASE WHEN rc.cancelled_at IS NULL THEN c.amount "
                "ELSE MIN(c.amount, COALESCE(uc.used, 0)) END")
_USED_SUBQ = ("(SELECT grant_id, SUM(credits) AS used FROM consumption_events "
              "WHERE bucket='grant' GROUP BY grant_id)")


class AccountingStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- cycles ---
    def add_cycle(self, c: Cycle) -> None:
        self.conn.execute(
            "INSERT INTO cycles (id,label,starts_at,ends_at,status) VALUES (?,?,?,?,?)",
            (c.id, c.label, c.starts_at, c.ends_at, c.status),
        )

    def get_cycle(self, cycle_id: str) -> Cycle | None:
        r = self.conn.execute("SELECT * FROM cycles WHERE id=?", (cycle_id,)).fetchone()
        return Cycle(r["id"], r["label"], r["starts_at"], r["ends_at"], r["status"]) if r else None

    def active_cycle(self) -> Cycle | None:
        r = self.conn.execute(
            "SELECT * FROM cycles WHERE status='active' ORDER BY starts_at DESC LIMIT 1"
        ).fetchone()
        return Cycle(r["id"], r["label"], r["starts_at"], r["ends_at"], r["status"]) if r else None

    # --- cycle report snapshots ---
    # A frozen, end-of-cycle report is stored once a cycle is archived so its
    # winner/donor labels can't drift as live user roles/names change later.
    def get_cycle_report(self, cycle_id: str) -> str | None:
        r = self.conn.execute(
            "SELECT report_json FROM cycle_reports WHERE cycle_id=?", (cycle_id,)
        ).fetchone()
        return r["report_json"] if r else None

    def save_cycle_report(self, cycle_id: str, report_json: str, now: int) -> None:
        self.conn.execute(
            "INSERT INTO cycle_reports (cycle_id, report_json, created_at) VALUES (?,?,?) "
            "ON CONFLICT(cycle_id) DO NOTHING",
            (cycle_id, report_json, now),
        )

    # --- giver_cycles ---
    def upsert_giver_cycle(self, gc: GiverCycle) -> None:
        self.conn.execute(
            "INSERT INTO giver_cycles (cycle_id,giver_id,quota,pledge) VALUES (?,?,?,?) "
            "ON CONFLICT(cycle_id,giver_id) DO UPDATE SET quota=excluded.quota, pledge=excluded.pledge",
            (gc.cycle_id, gc.giver_id, gc.quota, gc.pledge),
        )

    def get_giver_cycle(self, cycle_id: str, giver_id: str) -> GiverCycle | None:
        r = self.conn.execute(
            "SELECT * FROM giver_cycles WHERE cycle_id=? AND giver_id=?", (cycle_id, giver_id)
        ).fetchone()
        return GiverCycle(r["cycle_id"], r["giver_id"], r["quota"], r["pledge"]) if r else None

    def all_giver_cycles(self, cycle_id: str) -> list[GiverCycle]:
        rows = self.conn.execute("SELECT * FROM giver_cycles WHERE cycle_id=?", (cycle_id,)).fetchall()
        return [GiverCycle(r["cycle_id"], r["giver_id"], r["quota"], r["pledge"]) for r in rows]

    # --- requests ---
    @staticmethod
    def _request_row(r) -> Request:
        return Request(r["id"], r["cycle_id"], r["requester_id"], Role(r["requester_role"]),
                       r["amount_needed"], r["reason"], r["target"], r["created_at"],
                       r["expires_at"], r["cancelled_at"])

    def add_request(self, r: Request) -> None:
        self.conn.execute(
            "INSERT INTO requests (id,cycle_id,requester_id,requester_role,amount_needed,reason,target,created_at,expires_at,cancelled_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r.id, r.cycle_id, r.requester_id, r.requester_role.value, r.amount_needed,
             r.reason, r.target, r.created_at, r.expires_at, r.cancelled_at),
        )

    def get_request(self, request_id: str) -> Request | None:
        r = self.conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        return self._request_row(r) if r else None

    def cancel_request(self, request_id: str, now: int) -> None:
        self.conn.execute(
            "UPDATE requests SET cancelled_at=? WHERE id=? AND cancelled_at IS NULL",
            (now, request_id),
        )

    # --- grants ---
    @staticmethod
    def _grant_row(r) -> Grant:
        return Grant(r["id"], r["cycle_id"], r["request_id"], r["donor_id"],
                     r["recipient_id"], r["amount"], r["created_at"], r["source"],
                     r["origin_grant_id"], r["via_user_id"], r["contribution_id"])

    def add_grant(self, g: Grant) -> None:
        self.conn.execute(
            "INSERT INTO grants (id,cycle_id,request_id,donor_id,recipient_id,amount,created_at,source,"
            "origin_grant_id,via_user_id,contribution_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (g.id, g.cycle_id, g.request_id, g.donor_id, g.recipient_id, g.amount, g.created_at, g.source,
             g.origin_grant_id, g.via_user_id, g.contribution_id),
        )

    def get_grant(self, grant_id: str) -> Grant | None:
        r = self.conn.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()
        return self._grant_row(r) if r else None

    def grants_for_recipient(self, cycle_id: str, recipient_id: str) -> list[Grant]:
        rows = self.conn.execute(
            "SELECT * FROM grants WHERE cycle_id=? AND recipient_id=? ORDER BY created_at",
            (cycle_id, recipient_id),
        ).fetchall()
        return [self._grant_row(r) for r in rows]

    # --- pool contributions (received credit returned to the shared pool) ---
    @staticmethod
    def _contribution_row(r) -> PoolContribution:
        return PoolContribution(r["id"], r["cycle_id"], r["contributor_id"],
                                r["origin_grant_id"], r["donor_id"], r["amount"], r["created_at"])

    def add_pool_contribution(self, pc: PoolContribution) -> None:
        self.conn.execute(
            "INSERT INTO pool_contributions (id,cycle_id,contributor_id,origin_grant_id,donor_id,amount,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (pc.id, pc.cycle_id, pc.contributor_id, pc.origin_grant_id, pc.donor_id, pc.amount, pc.created_at),
        )

    def contributions_with_capacity(self, cycle_id: str) -> list[tuple[PoolContribution, int]]:
        # Each contribution's undrawn capacity, oldest first (the pool-draw
        # order). Drawn amounts are cancelled-aware so a cancelled TARGET
        # request refunds its unconsumed draw back into the contribution; a
        # cancelled ORIGIN request voids the undrawn capacity entirely.
        rows = self.conn.execute(
            "SELECT pc.*, CASE WHEN ro.cancelled_at IS NOT NULL THEN 0 "
            "             ELSE MAX(0, pc.amount - COALESCE(d.drawn, 0)) END AS capacity "
            "FROM pool_contributions pc "
            "JOIN grants og ON og.id = pc.origin_grant_id "
            "JOIN requests ro ON ro.id = og.request_id "
            "LEFT JOIN (SELECT c.contribution_id AS cid, "
            f"                 SUM({_LEAF_CHARGE}) AS drawn "
            "           FROM grants c "
            "           JOIN requests rc ON rc.id = c.request_id "
            f"          LEFT JOIN {_USED_SUBQ} uc ON uc.grant_id = c.id "
            "           WHERE c.contribution_id IS NOT NULL "
            "           GROUP BY c.contribution_id) d ON d.cid = pc.id "
            "WHERE pc.cycle_id=? "
            "ORDER BY pc.created_at, pc.id",
            (cycle_id,),
        ).fetchall()
        return [(self._contribution_row(r), int(r["capacity"] or 0)) for r in rows]

    def re_donated_by(self, cycle_id: str, user_id: str) -> int:
        # Received credit this user re-donated to other requests (cancelled-aware:
        # refunded transfers drop back out of this total).
        return self._sum(
            f"SELECT SUM({_LEAF_CHARGE}) "
            "FROM grants c "
            "JOIN requests rc ON rc.id = c.request_id "
            f"LEFT JOIN {_USED_SUBQ} uc ON uc.grant_id = c.id "
            "WHERE c.cycle_id=? AND c.via_user_id=? AND c.contribution_id IS NULL",
            (cycle_id, user_id),
        )

    def returned_to_pool_by(self, cycle_id: str, user_id: str) -> int:
        # Received credit this user moved into the shared pool. Counts the full
        # contribution while its origin request is live; after an origin cancel
        # only the part the pool already drew stays counted (the rest was voided).
        return self._sum(
            "SELECT SUM(CASE WHEN ro.cancelled_at IS NOT NULL THEN COALESCE(d.drawn, 0) "
            "            ELSE pc.amount END) "
            "FROM pool_contributions pc "
            "JOIN grants og ON og.id = pc.origin_grant_id "
            "JOIN requests ro ON ro.id = og.request_id "
            "LEFT JOIN (SELECT c.contribution_id AS cid, "
            f"                 SUM({_LEAF_CHARGE}) AS drawn "
            "           FROM grants c "
            "           JOIN requests rc ON rc.id = c.request_id "
            f"          LEFT JOIN {_USED_SUBQ} uc ON uc.grant_id = c.id "
            "           WHERE c.contribution_id IS NOT NULL "
            "           GROUP BY c.contribution_id) d ON d.cid = pc.id "
            "WHERE pc.cycle_id=? AND pc.contributor_id=?",
            (cycle_id, user_id),
        )

    # --- events ---
    def add_event(self, e: Event) -> None:
        self.conn.execute(
            "INSERT INTO consumption_events (id,cycle_id,ts,consumer_id,source_giver_id,bucket,grant_id,credits) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (e.id, e.cycle_id, e.ts, e.consumer_id, e.source_giver_id, e.bucket.value, e.grant_id, e.credits),
        )

    # --- aggregation primitives ---
    def _sum(self, sql: str, params: tuple) -> int:
        r = self.conn.execute(sql, params).fetchone()
        return int(r[0] or 0)

    def own_consumed(self, cycle_id: str, giver_id: str) -> int:
        return self._sum(
            "SELECT SUM(credits) FROM consumption_events WHERE cycle_id=? AND bucket='own' AND consumer_id=?",
            (cycle_id, giver_id),
        )

    def bypass_consumed(self, cycle_id: str, giver_id: str) -> int:
        return self._sum(
            "SELECT SUM(credits) FROM consumption_events WHERE cycle_id=? AND bucket='bypass' AND source_giver_id=?",
            (cycle_id, giver_id),
        )

    def pool_consumed_from(self, cycle_id: str, giver_id: str) -> int:
        return self._sum(
            "SELECT SUM(credits) FROM consumption_events WHERE cycle_id=? AND bucket='pool' AND source_giver_id=?",
            (cycle_id, giver_id),
        )

    def pool_consumed_by(self, cycle_id: str, consumer_id: str) -> int:
        return self._sum(
            "SELECT SUM(credits) FROM consumption_events WHERE cycle_id=? AND bucket='pool' AND consumer_id=?",
            (cycle_id, consumer_id),
        )

    def grant_consumed(self, cycle_id: str, grant_id: str) -> int:
        return self._sum(
            "SELECT SUM(credits) FROM consumption_events WHERE cycle_id=? AND bucket='grant' AND grant_id=?",
            (cycle_id, grant_id),
        )

    def _granted_out_by_source(self, cycle_id: str, donor_id: str, source: str) -> int:
        # A grant charges its donor in full while its request is live. Once the
        # request is cancelled, what stays charged is what the recipient burned
        # PLUS what they moved onward (re-donated child grants and pool draws of
        # their contributions, cancelled-aware themselves) — that credit is still
        # live downstream on the donor's PAT. Undrawn pool contributions of a
        # cancelled origin are voided (refund the donor, shrink the pool).
        # Child grants (origin_grant_id set) are excluded: they're funded by
        # their parent grant, not the donor's retained quota/pledge.
        return self._sum(
            "SELECT SUM(CASE WHEN r.cancelled_at IS NULL THEN g.amount "
            "            ELSE MIN(g.amount, COALESCE(u.used, 0) + COALESCE(t.moved, 0)) END) "
            "FROM grants g "
            "JOIN requests r ON r.id = g.request_id "
            f"LEFT JOIN {_USED_SUBQ} u ON u.grant_id = g.id "
            "LEFT JOIN (SELECT c.origin_grant_id AS oid, "
            f"                 SUM({_LEAF_CHARGE}) AS moved "
            "           FROM grants c "
            "           JOIN requests rc ON rc.id = c.request_id "
            f"          LEFT JOIN {_USED_SUBQ} uc ON uc.grant_id = c.id "
            "           WHERE c.origin_grant_id IS NOT NULL "
            "           GROUP BY c.origin_grant_id) t ON t.oid = g.id "
            "WHERE g.cycle_id=? AND g.donor_id=? AND g.source=? AND g.origin_grant_id IS NULL",
            (cycle_id, donor_id, source),
        )

    def transferred_out(self, grant_id: str) -> int:
        # Credit re-donated onward out of this grant (direct child grants only —
        # pool draws charge the contribution instead). Cancelled-aware: if the
        # target request is cancelled, the unconsumed part refunds back into the
        # parent grant's remaining (i.e. to the re-donor's received balance).
        return self._sum(
            f"SELECT SUM({_LEAF_CHARGE}) "
            "FROM grants c "
            "JOIN requests rc ON rc.id = c.request_id "
            f"LEFT JOIN {_USED_SUBQ} uc ON uc.grant_id = c.id "
            "WHERE c.origin_grant_id=? AND c.contribution_id IS NULL",
            (grant_id,),
        )

    def contribution_drawn_for_origin(self, grant_id: str) -> int:
        # Pool draws (cancelled-aware) of contributions chained to this origin
        # grant — the part of a cancelled origin's contributions that stays
        # charged (the undrawn part is voided back to the donor).
        return self._sum(
            f"SELECT SUM({_LEAF_CHARGE}) "
            "FROM grants c "
            "JOIN requests rc ON rc.id = c.request_id "
            f"LEFT JOIN {_USED_SUBQ} uc ON uc.grant_id = c.id "
            "WHERE c.origin_grant_id=? AND c.contribution_id IS NOT NULL",
            (grant_id,),
        )

    def contributed_out(self, grant_id: str) -> int:
        # Credit moved from this grant into the shared pool. Charged in full
        # while the origin request is live (grant_remaining is 0 after cancel
        # anyway, and the cancel-time void is handled in _granted_out_by_source).
        return self._sum(
            "SELECT SUM(amount) FROM pool_contributions WHERE origin_grant_id=?",
            (grant_id,),
        )

    def granted_out(self, cycle_id: str, donor_id: str) -> int:
        # Personal chip-ins charged against the donor's personal credit.
        return self._granted_out_by_source(cycle_id, donor_id, "personal")

    def pool_granted_out(self, cycle_id: str, giver_id: str) -> int:
        # Pool fills attributed to this giver, charged against their pledge.
        return self._granted_out_by_source(cycle_id, giver_id, "pool")

    def grants_count_by(self, cycle_id: str, donor_id: str) -> int:
        # Counts the human act: re-donations count for the re-donor (via_user_id),
        # not the original PAT holder they chain back to.
        return self._sum(
            "SELECT COUNT(*) FROM grants WHERE cycle_id=? AND COALESCE(via_user_id, donor_id)=?",
            (cycle_id, donor_id),
        )

    def grants_consumed_from(self, cycle_id: str, giver_id: str) -> int:
        # Credit actually drawn by recipients from THIS giver's grants — ALL
        # sources. Feeds reconcile_giver's drift watermark, which must include
        # pool-funded grants (they burn the giver's real upstream quota too).
        return self._sum(
            "SELECT SUM(credits) FROM consumption_events "
            "WHERE cycle_id=? AND bucket='grant' AND source_giver_id=?",
            (cycle_id, giver_id),
        )

    def personal_grants_consumed_from(self, cycle_id: str, giver_id: str) -> int:
        # Same, restricted to personal chip-ins — profile "donated consumed".
        return self._sum(
            "SELECT SUM(ce.credits) FROM consumption_events ce "
            "JOIN grants g ON g.id = ce.grant_id "
            "WHERE ce.cycle_id=? AND ce.bucket='grant' AND ce.source_giver_id=? "
            "AND g.source='personal'",
            (cycle_id, giver_id),
        )

    def pool_grants_consumed_from(self, cycle_id: str, giver_id: str) -> int:
        # Pool-fill consumption attributed to this giver's pledge.
        return self._sum(
            "SELECT SUM(ce.credits) FROM consumption_events ce "
            "JOIN grants g ON g.id = ce.grant_id "
            "WHERE ce.cycle_id=? AND ce.bucket='grant' AND ce.source_giver_id=? "
            "AND g.source='pool'",
            (cycle_id, giver_id),
        )

    def consumed_total(self, cycle_id: str, user_id: str) -> int:
        return self._sum(
            "SELECT SUM(credits) FROM consumption_events WHERE cycle_id=? AND consumer_id=?",
            (cycle_id, user_id),
        )

    def donated_live(self, cycle_id: str, giver_id: str) -> int:
        return self._sum(
            "SELECT SUM(credits) FROM consumption_events "
            "WHERE cycle_id=? AND source_giver_id=? AND consumer_id<>?",
            (cycle_id, giver_id, giver_id),
        )

    def consumed_from_others(self, cycle_id: str, user_id: str) -> int:
        # Credit this user drew from OTHER givers' gifts — pool draws plus grants
        # received — excluding their own quota (own bucket is self-sourced). The
        # symmetric counterpart of donated_live (others burning this user's gifts).
        return self._sum(
            "SELECT SUM(credits) FROM consumption_events "
            "WHERE cycle_id=? AND consumer_id=? AND source_giver_id<>?",
            (cycle_id, user_id, user_id),
        )

    def request_funded(self, request_id: str) -> int:
        return self._sum("SELECT SUM(amount) FROM grants WHERE request_id=?", (request_id,))

    def request_consumed(self, request_id: str) -> int:
        # Credit the recipient has actually burned out of this request's grants —
        # grant-bucket consumption joined to the grants funding this request. Lets
        # the marketplace card show how much of the raised credit has been used.
        return self._sum(
            "SELECT SUM(ce.credits) FROM consumption_events ce "
            "JOIN grants g ON g.id = ce.grant_id "
            "WHERE ce.bucket='grant' AND g.request_id=?",
            (request_id,),
        )

    def list_requests(self, cycle_id: str) -> list[Request]:
        rows = self.conn.execute(
            "SELECT * FROM requests WHERE cycle_id=? AND cancelled_at IS NULL "
            "ORDER BY created_at DESC, id DESC",
            (cycle_id,),
        ).fetchall()
        return [self._request_row(r) for r in rows]

    def request_donor_count(self, request_id: str) -> int:
        # Individual supporters: personal chip-ins by donor, plus re-donations
        # by their via user (a re-donation of pool-source credit still has a
        # human supporter). Anonymous pool draws don't count.
        r = self.conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(via_user_id, donor_id)) FROM grants "
            "WHERE request_id=? AND (source='personal' OR via_user_id IS NOT NULL)",
            (request_id,),
        ).fetchone()
        return int(r[0] or 0)

    def request_pool_funded(self, request_id: str) -> int:
        return self._sum(
            "SELECT SUM(amount) FROM grants WHERE request_id=? AND source='pool'",
            (request_id,),
        )
