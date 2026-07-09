from __future__ import annotations

import sqlite3


class AuthStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_user(self, user_id, ghe_login, display_name, role, now):
        self.conn.execute(
            "INSERT INTO users (id, ghe_login, display_name, role, created_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(ghe_login) DO NOTHING",
            (user_id, ghe_login, display_name, role, now),
        )

    def get_user_by_login(self, ghe_login):
        r = self.conn.execute("SELECT * FROM users WHERE ghe_login=?", (ghe_login,)).fetchone()
        return dict(r) if r else None

    def get_user_by_id(self, user_id):
        r = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(r) if r else None

    def set_user_role(self, user_id, role):
        self.conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))

    def set_onboarded(self, user_id):
        self.conn.execute("UPDATE users SET onboarded=1 WHERE id=?", (user_id,))

    def list_users(self):
        rows = self.conn.execute(
            "SELECT id, ghe_login, display_name, role FROM users ORDER BY created_at, id"
        ).fetchall()
        return [dict(r) for r in rows]

    def search_users(self, q, limit=8):
        like = f"%{q}%"
        rows = self.conn.execute(
            "SELECT id, ghe_login, display_name, role FROM users "
            "WHERE display_name LIKE ? COLLATE NOCASE OR ghe_login LIKE ? COLLATE NOCASE "
            "ORDER BY created_at, id LIMIT ?",
            (like, like, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_proxy_token(self, id, token_hash, user_id, fingerprint, now):
        self.conn.execute(
            "INSERT INTO proxy_tokens (id, token_hash, user_id, fingerprint, created_at) "
            "VALUES (?,?,?,?,?)",
            (id, token_hash, user_id, fingerprint, now),
        )

    def get_active_proxy_token(self, token_hash):
        r = self.conn.execute(
            "SELECT * FROM proxy_tokens WHERE token_hash=? AND revoked_at IS NULL", (token_hash,)
        ).fetchone()
        return dict(r) if r else None

    def list_proxy_tokens(self, user_id):
        rows = self.conn.execute(
            "SELECT id, fingerprint, created_at, revoked_at FROM proxy_tokens "
            "WHERE user_id=? ORDER BY created_at", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def revoke_proxy_token(self, id, user_id, now):
        cur = self.conn.execute(
            "UPDATE proxy_tokens SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL",
            (now, id, user_id),
        )
        return cur.rowcount > 0

    def set_giver_pat(self, user_id, ciphertext, nonce, fingerprint, now):
        self.conn.execute(
            "INSERT INTO giver_pats (user_id, ciphertext, nonce, fingerprint, created_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
            "ciphertext=excluded.ciphertext, nonce=excluded.nonce, "
            "fingerprint=excluded.fingerprint, created_at=excluded.created_at",
            (user_id, ciphertext, nonce, fingerprint, now),
        )

    def get_giver_pat(self, user_id):
        r = self.conn.execute("SELECT * FROM giver_pats WHERE user_id=?", (user_id,)).fetchone()
        return dict(r) if r else None

    def delete_giver_pat(self, user_id):
        self.conn.execute("DELETE FROM giver_pats WHERE user_id=?", (user_id,))

    def set_giver_quota_snapshot(self, user_id, entitlement, remaining, reset_date, now):
        self.conn.execute(
            "UPDATE giver_pats SET entitlement=?, remaining_at_submit=?, quota_reset_date=? "
            "WHERE user_id=?",
            (entitlement, remaining, reset_date, user_id),
        )

    def get_giver_quota_snapshot(self, user_id):
        r = self.conn.execute(
            "SELECT entitlement, remaining_at_submit, quota_reset_date FROM giver_pats WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if r is None or r["entitlement"] is None:
            return None
        return {"entitlement": r["entitlement"],
                "remaining_at_submit": r["remaining_at_submit"],
                "quota_reset_date": r["quota_reset_date"]}

    def set_pat_health_ok(self, user_id, status, now):
        """Record a definitive health verdict (valid/expired/forbidden/no_entitlement)."""
        self.conn.execute(
            "UPDATE giver_pats SET health_status=?, health_error=NULL, health_checked_at=? "
            "WHERE user_id=?",
            (status, now, user_id),
        )

    def set_pat_health_error(self, user_id, error, now):
        """Record an indefinitive check (network/5xx): keep the last verdict."""
        self.conn.execute(
            "UPDATE giver_pats SET health_error=?, health_checked_at=? WHERE user_id=?",
            (error, now, user_id),
        )

    def get_pat_health(self, user_id):
        r = self.conn.execute(
            "SELECT health_status, health_checked_at, health_error FROM giver_pats WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if r is None:
            return None
        return {"status": r["health_status"], "checked_at": r["health_checked_at"],
                "error": r["health_error"]}

    def list_giver_ids(self):
        return [r["user_id"] for r in self.conn.execute("SELECT user_id FROM giver_pats").fetchall()]

    def create_session(self, id, user_id, now, ttl_s):
        self.conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (id, user_id, now, now + ttl_s),
        )

    def get_active_session(self, id, now):
        r = self.conn.execute(
            "SELECT * FROM sessions WHERE id=? AND expires_at > ?", (id, now)
        ).fetchone()
        return dict(r) if r else None

    def revoke_session(self, id):
        self.conn.execute("DELETE FROM sessions WHERE id=?", (id,))

    def list_users_admin(self):
        rows = self.conn.execute(
            "SELECT u.id, u.ghe_login, u.display_name, u.role, u.onboarded, "
            "       p.fingerprint AS pat_fingerprint, "
            "       p.health_status AS pat_health_status, "
            "       p.health_checked_at AS pat_health_checked_at, "
            "       p.health_error AS pat_health_error, "
            "       (SELECT COUNT(*) FROM proxy_tokens t WHERE t.user_id = u.id) AS token_count "
            "FROM users u LEFT JOIN giver_pats p ON p.user_id = u.id "
            "ORDER BY u.created_at, u.id"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_admin_audit(self, id, admin_id, admin_login, action, target_user_id, now):
        self.conn.execute(
            "INSERT INTO admin_audit (id, admin_id, admin_login, action, target_user_id, ts) "
            "VALUES (?,?,?,?,?,?)",
            (id, admin_id, admin_login, action, target_user_id, now),
        )

    def list_admin_audit(self):
        rows = self.conn.execute(
            "SELECT * FROM admin_audit ORDER BY ts DESC, id"
        ).fetchall()
        return [dict(r) for r in rows]
