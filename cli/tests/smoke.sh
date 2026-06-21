#!/usr/bin/env bash
# Real-binary smoke: ctc login + ctc against a locally-running proxy.py.
# Requires: a running proxy (see TDD §6.2), repo cert.pem, a real copilot binary,
# and env REAL_TEST_TOKEN (a fake-but-well-formed token the proxy will accept).
# Usage: CTC_HOST=localhost REAL_TEST_TOKEN=github_pat_... bash cli/tests/smoke.sh
set -euo pipefail

: "${REAL_TEST_TOKEN:?set REAL_TEST_TOKEN}"
export CTC_HOST="${CTC_HOST:-localhost}" CTC_PROXY_PORT="${CTC_PROXY_PORT:-8080}"
SANDBOX="$(mktemp -d)"; trap 'rm -rf "$SANDBOX"' EXIT
export HOME="$SANDBOX"; export XDG_CONFIG_HOME="$HOME/.config"

# Serve the repo cert.pem where 'ctc login' expects to download it, by stubbing curl.
STUBS="$SANDBOX/stubs"; mkdir -p "$STUBS"; export PATH="$STUBS:$PATH"
repo_cert="$(cd "$(dirname "$0")/../.." && pwd)/cert.pem"
cat > "$STUBS/curl" <<EOF
#!/bin/sh
prev=""
for a in "\$@"; do
  [ "\$prev" = "-o" ] && cp "$repo_cert" "\$a"
  prev="\$a"
done
EOF
chmod +x "$STUBS/curl"

echo "$REAL_TEST_TOKEN" | "$(dirname "$0")/../ctc" login
echo "Running a one-shot Copilot prompt through CTC ..."
"$(dirname "$0")/../ctc" -p "say the single word: pong" || { echo "SMOKE FAIL: copilot run failed"; exit 1; }
echo "SMOKE OK — request completed through the proxy. Check proxy logs for the session= attribution."
