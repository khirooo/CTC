test_install_places_ctc_and_patches_path() {
  setup_sandbox
  export SHELL=/bin/zsh                       # rc detection target
  # serve the real ctc from the repo via a file:// source the installer can copy
  CTC_SRC="$CTC_BIN" sh "$(dirname "$CTC_BIN")/install.sh" >/dev/null 2>&1
  code=$?
  assert_exit "$code" 0 "install exits 0"
  [ -x "$HOME/.local/bin/ctc" ] && echo "  ok: ctc installed + executable" || { echo "  FAIL: ctc not installed"; TESTS_FAILED=$((TESTS_FAILED+1)); }; TESTS_RUN=$((TESTS_RUN+1))
  assert_contains "$(cat "$HOME/.zshrc" 2>/dev/null || echo '')" ".local/bin" "PATH patched in rc"
}

test_install_uses_insecure_flag_for_http_source() {
  setup_sandbox
  export SHELL=/bin/zsh
  # Stub curl to log args and produce a fake binary at the -o target.
  make_stub curl 'prev=""; for a in "$@"; do if [ "$prev" = "-o" ]; then printf "#!/bin/sh\n" > "$a"; fi; prev="$a"; done'
  CTC_SRC="https://ctc.local/ctc" sh "$(dirname "$CTC_BIN")/install.sh" </dev/null >/dev/null 2>&1 || true
  assert_contains "$(cat "$SANDBOX/curl.log")" "-fsSLk" "install.sh fetches /ctc with -fsSLk"
  teardown_sandbox
}
