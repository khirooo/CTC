from __future__ import annotations


def admins_from_env(env) -> frozenset[str]:
    raw = (env.get("CTC_ADMINS") or "").strip()
    if not raw:
        return frozenset()
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def is_admin(login: str, admins) -> bool:
    return bool(login) and login.lower() in admins
