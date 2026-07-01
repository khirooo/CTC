from __future__ import annotations

import sqlite3

from ..domain.types import Bucket, Cycle, Event, Grant, GiverCycle, Request, Role


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
    def add_request(self, r: Request) -> None:
        self.conn.execute(
            "INSERT INTO requests (id,cycle_id,requester_id,requester_role,amount_needed,reason,target,created_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (r.id, r.cycle_id, r.requester_id, r.requester_role.value, r.amount_needed,
             r.reason, r.target, r.created_at, r.expires_at),
        )

    def get_request(self, request_id: str) -> Request | None:
        r = self.conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if not r:
            return None
        return Request(r["id"], r["cycle_id"], r["requester_id"], Role(r["requester_role"]),
                       r["amount_needed"], r["reason"], r["target"], r["created_at"], r["expires_at"])

    # --- grants ---
    def add_grant(self, g: Grant) -> None:
        self.conn.execute(
            "INSERT INTO grants (id,cycle_id,request_id,donor_id,recipient_id,amount,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (g.id, g.cycle_id, g.request_id, g.donor_id, g.recipient_id, g.amount, g.created_at),
        )

    def get_grant(self, grant_id: str) -> Grant | None:
        r = self.conn.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()
        if not r:
            return None
        return Grant(r["id"], r["cycle_id"], r["request_id"], r["donor_id"],
                     r["recipient_id"], r["amount"], r["created_at"])

    def grants_for_recipient(self, cycle_id: str, recipient_id: str) -> list[Grant]:
        rows = self.conn.execute(
            "SELECT * FROM grants WHERE cycle_id=? AND recipient_id=? ORDER BY created_at",
            (cycle_id, recipient_id),
        ).fetchall()
        return [Grant(r["id"], r["cycle_id"], r["request_id"], r["donor_id"],
                      r["recipient_id"], r["amount"], r["created_at"]) for r in rows]

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

    def granted_out(self, cycle_id: str, donor_id: str) -> int:
        return self._sum(
            "SELECT SUM(amount) FROM grants WHERE cycle_id=? AND donor_id=?",
            (cycle_id, donor_id),
        )

    def grants_count_by(self, cycle_id: str, donor_id: str) -> int:
        return self._sum(
            "SELECT COUNT(*) FROM grants WHERE cycle_id=? AND donor_id=?",
            (cycle_id, donor_id),
        )

    def grants_consumed_from(self, cycle_id: str, giver_id: str) -> int:
        # Credit actually drawn by recipients from THIS giver's grants (solid green).
        return self._sum(
            "SELECT SUM(credits) FROM consumption_events "
            "WHERE cycle_id=? AND bucket='grant' AND source_giver_id=?",
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
            "SELECT * FROM requests WHERE cycle_id=? ORDER BY created_at DESC, id DESC",
            (cycle_id,),
        ).fetchall()
        return [Request(r["id"], r["cycle_id"], r["requester_id"], Role(r["requester_role"]),
                        r["amount_needed"], r["reason"], r["target"], r["created_at"], r["expires_at"])
                for r in rows]

    def request_donor_count(self, request_id: str) -> int:
        r = self.conn.execute(
            "SELECT COUNT(DISTINCT donor_id) FROM grants WHERE request_id=?", (request_id,)
        ).fetchone()
        return int(r[0] or 0)
