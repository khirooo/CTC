#!/usr/bin/env sh
# Preflight checks for a CTC deployment. Run from the repo root BEFORE
# `docker compose up`. Validates tooling, .env presence, required variables
# (per auth/email mode), and web-transport consistency. Never prints secret
# values. Exits non-zero on the first class of hard failures it finds.
set -eu

FAIL=0
fail() { printf 'ERROR: %s\n' "$1" >&2; FAIL=1; }
warn() { printf 'WARN:  %s\n' "$1" >&2; }

# --- tooling ---
command -v docker >/dev/null 2>&1 || fail "docker not found on PATH"
docker compose version >/dev/null 2>&1 || fail "'docker compose' not available (need Compose v2)"

# --- .env presence ---
if [ ! -f .env ]; then
  fail ".env not found in $(pwd) — copy .env.example to .env and fill it in"
  printf '\nPreflight FAILED.\n' >&2
  exit 1
fi

# Load .env without exporting secrets into child processes we spawn for output.
# shellcheck disable=SC1091
set -a; . ./.env; set +a

# Apply the same defaults compose/the app use, so we validate what will run.
CTC_AUTH_MODE="${CTC_AUTH_MODE:-email}"
CTC_EMAIL_BACKEND="${CTC_EMAIL_BACKEND:-console}"
CTC_WEB_TRANSPORT="${CTC_WEB_TRANSPORT:-http}"
CADDYFILE="${CADDYFILE:-Caddyfile}"
PROXY_BIND="${PROXY_BIND:-127.0.0.1}"

# --- placeholder / required core vars ---
[ -n "${CTC_DOMAIN:-}" ] || fail "CTC_DOMAIN is unset"
if [ -z "${CTC_SECRET_KEY:-}" ]; then
  fail "CTC_SECRET_KEY is unset"
elif [ "${CTC_SECRET_KEY}" = "change-me-to-a-long-random-secret" ]; then
  fail "CTC_SECRET_KEY is still the example placeholder — generate one (openssl rand -hex 32)"
elif [ "${#CTC_SECRET_KEY}" -lt 32 ]; then
  warn "CTC_SECRET_KEY is shorter than 32 characters — use a longer random value"
fi
[ -n "${GHE_DOMAIN:-}" ]    || fail "GHE_DOMAIN is unset"
[ -n "${GHE_API_BASE:-}" ]  || fail "GHE_API_BASE is unset"
[ -n "${REAL_GHE_HOST:-}" ] || fail "REAL_GHE_HOST is unset"

# --- mode-specific required vars ---
if [ "$CTC_AUTH_MODE" = "ghe_oauth" ]; then
  [ -n "${GHE_OAUTH_CLIENT_ID:-}" ]     || fail "CTC_AUTH_MODE=ghe_oauth but GHE_OAUTH_CLIENT_ID is unset"
  [ -n "${GHE_OAUTH_CLIENT_SECRET:-}" ] || fail "CTC_AUTH_MODE=ghe_oauth but GHE_OAUTH_CLIENT_SECRET is unset"
  [ -n "${GHE_OAUTH_BASE:-}" ]          || fail "CTC_AUTH_MODE=ghe_oauth but GHE_OAUTH_BASE is unset"
fi

if [ "$CTC_EMAIL_BACKEND" = "smtp" ]; then
  [ -n "${CTC_SMTP_HOST:-}" ] || fail "CTC_EMAIL_BACKEND=smtp but CTC_SMTP_HOST is unset"
  [ -n "${CTC_SMTP_FROM:-}" ] || fail "CTC_EMAIL_BACKEND=smtp but CTC_SMTP_FROM is unset"
fi

# --- transport consistency ---
case "$CTC_WEB_TRANSPORT" in
  https)
    [ "$CADDYFILE" = "Caddyfile" ] || fail "CTC_WEB_TRANSPORT=https requires CADDYFILE=Caddyfile (got '$CADDYFILE')" ;;
  http)
    [ "$CADDYFILE" = "Caddyfile.http" ] || fail "CTC_WEB_TRANSPORT=http requires CADDYFILE=Caddyfile.http (got '$CADDYFILE')" ;;
  *)
    fail "CTC_WEB_TRANSPORT must be 'http' or 'https' (got '$CTC_WEB_TRANSPORT')" ;;
esac
[ -f "$CADDYFILE" ] || fail "selected CADDYFILE '$CADDYFILE' does not exist in $(pwd)"

# --- non-fatal warnings ---
[ "$PROXY_BIND" = "127.0.0.1" ] && warn "PROXY_BIND=127.0.0.1 — the proxy is localhost-only; teammates on the VPN can't reach :8080"

if [ "$FAIL" -ne 0 ]; then
  printf '\nPreflight FAILED — fix the errors above before running docker compose up.\n' >&2
  exit 1
fi
printf 'Preflight OK.\n'
