#!/usr/bin/env sh
# migrate-restore.sh — load a CTC backup onto a NEW server.
#
# Restores the SQLite DB into a fresh ctcdata volume and drops .env into place,
# then stops so you can adjust the new server's address before first boot.
# It deliberately does NOT run `docker compose up` — you're on a new IP, so
# .env needs three edits first (see NEXT STEPS printed at the end).
#
# Run from the repo root on the NEW server (after cloning the repo):
#   sh scripts/migrate-restore.sh ctc-backup-<timestamp>.tar.gz
#
# Refuses to clobber an existing populated DB volume unless FORCE=1.
set -eu

ARCHIVE="${1:-}"
[ -n "$ARCHIVE" ] || { echo "usage: sh scripts/migrate-restore.sh <backup.tar.gz>" >&2; exit 2; }

PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$(pwd)" | tr '[:upper:]' '[:lower:]')}"
DB_VOLUME="${CTC_DB_VOLUME:-${PROJECT}_ctcdata}"
TS="$(date +%Y%m%d-%H%M%S)"
STAGING="$(pwd)/.migrate-restore-${TS}"

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- preflight -------------------------------------------------------------
[ -f docker-compose.yml ] || fail "run this from the repo root (no docker-compose.yml here)"
[ -f "$ARCHIVE" ]         || fail "backup archive not found: $ARCHIVE"
command -v docker >/dev/null 2>&1 || fail "docker not found"

echo "==> project=$PROJECT  db-volume=$DB_VOLUME"

# Guard against overwriting an existing populated DB.
if docker volume inspect "$DB_VOLUME" >/dev/null 2>&1; then
  EXISTING="$(docker run --rm -v "$DB_VOLUME:/data" alpine sh -c '[ -s /data/ctc.db ] && echo yes || echo no')"
  if [ "$EXISTING" = "yes" ] && [ "${FORCE:-0}" != "1" ]; then
    fail "volume '$DB_VOLUME' already has a ctc.db. Re-run with FORCE=1 to overwrite it."
  fi
fi

# --- unpack ----------------------------------------------------------------
mkdir -p "$STAGING"
trap 'rm -rf "$STAGING"' EXIT
tar xzf "$ARCHIVE" -C "$STAGING"
[ -s "$STAGING/ctc.db" ] || fail "archive has no ctc.db"
[ -f "$STAGING/.env" ]   || fail "archive has no .env"

# --- restore .env (preserving any local one) -------------------------------
if [ -f .env ]; then
  cp .env ".env.pre-migrate-${TS}"
  echo "==> existing .env saved to .env.pre-migrate-${TS}"
fi
cp "$STAGING/.env" .env
echo "==> .env restored (CTC_SECRET_KEY preserved — DO NOT change it)"

# --- load DB into a fresh volume, owned by uid 10001 (the app's 'ctc' user) -
docker volume create "$DB_VOLUME" >/dev/null
docker run --rm -v "$DB_VOLUME:/data" -v "$STAGING:/in" alpine \
  sh -c "cp /in/ctc.db /data/ctc.db && chown 10001:10001 /data/ctc.db && chmod 640 /data/ctc.db && echo '  db loaded into volume'" \
  || fail "loading DB into volume failed"

# --- done ------------------------------------------------------------------
cat <<EOF

==> DB + .env restored into project '$PROJECT'.

NEXT STEPS (the server's address changed, so edit .env before booting):

  1. Edit .env for the new server:
       CTC_DOMAIN=<new IP or hostname>
       PROXY_BIND=<new VM's VPN-facing IP>
       GITLAB_OAUTH_REDIRECT_URI=https://<new CTC_DOMAIN>/auth/callback
     Leave CTC_SECRET_KEY exactly as-is (it must match the restored DB).

  2. In GitLab → the CTC OAuth app, update the Redirect URI to match the new
     GITLAB_OAUTH_REDIRECT_URI above (a mismatch is the #1 cause of broken login).

  3. Validate + boot:
       sh scripts/preflight.sh
       docker compose up -d --build
       docker compose ps        # all three healthy?

  4. Verify nothing was lost: log in via GitLab → your account, credit balance,
     and (as admin) a giver PAT reveal should all be intact.

  Teammates re-run the install one-liner from the new domain (new proxy address +
  fresh cert) — expected on an IP change.
EOF
