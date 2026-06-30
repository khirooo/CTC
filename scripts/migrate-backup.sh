#!/usr/bin/env sh
# migrate-backup.sh — snapshot CTC prod state for moving to another server.
#
# Captures the ONLY two things that can't be rebuilt from the repo:
#   1. the SQLite DB  (ctc_ctcdata volume → /data/ctc.db) — users, encrypted
#      PATs, all credit/ledger history;
#   2. .env           — crucially CTC_SECRET_KEY, the key the DB was encrypted
#      with. The DB is useless without the exact same key.
#
# The MITM cert (ctc_ctccerts) and Caddy's LE cert (ctc_caddydata) are NOT
# captured: you're moving to a new IP, so every client re-runs the install
# one-liner anyway (the proxy address changes), and gencert mints a fresh MITM
# cert + Caddy refetches its cert automatically on the new box.
#
# Run from the repo root on the OLD server, with the stack running:
#   sh scripts/migrate-backup.sh
#
# Produces ./ctc-backup-<timestamp>.tar.gz  (chmod 600 — contains secrets).
set -eu

PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$(pwd)" | tr '[:upper:]' '[:lower:]')}"
DB_VOLUME="${CTC_DB_VOLUME:-${PROJECT}_ctcdata}"
TS="$(date +%Y%m%d-%H%M%S)"
STAGING="$(pwd)/.migrate-staging-${TS}"
ARCHIVE="$(pwd)/ctc-backup-${TS}.tar.gz"

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- preflight -------------------------------------------------------------
[ -f docker-compose.yml ] || fail "run this from the repo root (no docker-compose.yml here)"
[ -f .env ]               || fail ".env not found — nothing to back up the secret key from"
command -v docker >/dev/null 2>&1 || fail "docker not found"
docker volume inspect "$DB_VOLUME" >/dev/null 2>&1 \
  || fail "volume '$DB_VOLUME' not found. Set CTC_DB_VOLUME=<name> (see: docker volume ls | grep ctcdata)"

echo "==> project=$PROJECT  db-volume=$DB_VOLUME"
mkdir -p "$STAGING"
chmod 777 "$STAGING"   # so the container's uid 10001 can write here
trap 'rm -rf "$STAGING"' EXIT

# --- consistent online backup of the live SQLite DB ------------------------
# Uses sqlite3's .backup via the already-built project image (python3.12-slim),
# which has the ctcdata volume mounted at /data. Safe while the stack is up
# (atomic snapshot — no torn WAL).
echo "==> snapshotting /data/ctc.db (online, consistent)…"
docker compose run --rm --no-deps -v "$STAGING:/out" proxy \
  python -c "import sqlite3,sys; src=sqlite3.connect('/data/ctc.db'); dst=sqlite3.connect('/out/ctc.db'); src.backup(dst); dst.close(); src.close(); print('  db snapshot ok')" \
  || fail "DB snapshot failed (is the stack built/running? try: docker compose up -d)"

[ -s "$STAGING/ctc.db" ] || fail "snapshot produced an empty DB — aborting"

# --- bundle .env alongside it ----------------------------------------------
cp .env "$STAGING/.env"
cat > "$STAGING/MANIFEST.txt" <<EOF
CTC migration backup
created:        $TS
source-project: $PROJECT
source-volume:  $DB_VOLUME
contents:       ctc.db (SQLite snapshot), .env (secrets incl. CTC_SECRET_KEY)
restore with:   sh scripts/migrate-restore.sh ctc-backup-${TS}.tar.gz
EOF

# --- pack ------------------------------------------------------------------
tar czf "$ARCHIVE" -C "$STAGING" ctc.db .env MANIFEST.txt
chmod 600 "$ARCHIVE"

SIZE="$(du -h "$ARCHIVE" | cut -f1)"
echo
echo "==> backup written: $ARCHIVE  ($SIZE)"
command -v sha256sum >/dev/null 2>&1 && echo "    sha256: $(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
echo
echo "Next:"
echo "  1. Copy it to the new server (it contains CTC_SECRET_KEY — use scp/secure transfer):"
echo "       scp $ARCHIVE newserver:/path/to/CTC/"
echo "  2. On the new server, in the repo root: sh scripts/migrate-restore.sh $(basename "$ARCHIVE")"
echo "  3. Delete this local copy once transferred:  rm $ARCHIVE"
