# Test helpers — sandboxed bash test harness (no external deps).
set -u
TESTS_RUN=0; TESTS_FAILED=0
CTC_BIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/ctc"

setup_sandbox() {
  SANDBOX="$(mktemp -d)"
  export HOME="$SANDBOX/home"; mkdir -p "$HOME"
  export XDG_CONFIG_HOME="$HOME/.config"
  STUBS="$SANDBOX/stubs"; mkdir -p "$STUBS"
  export PATH="$STUBS:$PATH"
  unset XDG_STATE_HOME XDG_CACHE_HOME 2>/dev/null || true
}
teardown_sandbox() { rm -rf "$SANDBOX"; }

# make_stub NAME BODY  -> creates an executable $STUBS/NAME logging calls to $SANDBOX/NAME.log
make_stub() {
  local name="$1" body="$2"
  { printf '#!/bin/sh\necho "$@" >> "%s/%s.log"\n%s\n' "$SANDBOX" "$name" "$body"; } > "$STUBS/$name"
  chmod +x "$STUBS/$name"
}

assert_contains() { # haystack needle msg
  TESTS_RUN=$((TESTS_RUN+1))
  case "$1" in *"$2"*) echo "  ok: $3";; *) echo "  FAIL: $3"; echo "    expected to contain: $2"; echo "    got: $1"; TESTS_FAILED=$((TESTS_FAILED+1));; esac
}
assert_exit() { # actual expected msg
  TESTS_RUN=$((TESTS_RUN+1))
  if [ "$1" = "$2" ]; then echo "  ok: $3"; else echo "  FAIL: $3 (exit $1, expected $2)"; TESTS_FAILED=$((TESTS_FAILED+1)); fi
}
