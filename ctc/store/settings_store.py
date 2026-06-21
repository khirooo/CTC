from __future__ import annotations

import sqlite3


class SettingsStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_all(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def set_many(self, items: dict[str, str], updated_by, now: int) -> None:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for k, v in items.items():
                self.conn.execute(
                    "INSERT INTO settings (key, value, updated_at, updated_by) VALUES (?,?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                    "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                    (k, v, now, updated_by),
                )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
