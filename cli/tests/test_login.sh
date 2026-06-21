_stub_login_env() {
  make_stub security ':'                       # trust succeeds, no-op
  make_stub sudo 'exec "$@"'                    # run the wrapped command directly
  make_stub curl 'prev=""; for a in "$@"; do if [ "$prev" = "-o" ]; then printf "FAKECERT" > "$a"; fi; prev="$a"; done'
  make_stub openssl 'echo "sha256 Fingerprint=AA:BB:CC:DD"'   # deterministic fingerprint
}

test_login_writes_env_and_cert() {
  setup_sandbox; _stub_login_env
  printf 'github_pat_TESTTOKEN1234\n' | "$CTC_BIN" login >/dev/null 2>&1
  code=$?
  assert_exit "$code" 0 "login exits 0"
  cfg="$HOME/.config/ctc"
  assert_contains "$(cat "$cfg/ca.pem")" "FAKECERT" "cert downloaded"
  assert_contains "$(cat "$SANDBOX/curl.log")" "-fsSLk" "CA fetched with -k"
  env="$(cat "$cfg/env")"
  assert_contains "$env" "COPILOT_GITHUB_TOKEN=\"github_pat_TESTTOKEN1234\"" "token written"
  assert_contains "$env" "GH_HOST=example.ghe.com" "GH_HOST written"
  assert_contains "$env" "HTTPS_PROXY=\"http://ctc.local:8080\"" "proxy written"
  assert_contains "$env" "HOME=\"$cfg/home\"" "isolated HOME written"
  assert_contains "$env" "NODE_EXTRA_CA_CERTS=\"$cfg/ca.pem\"" "cert path written"
  [ -d "$cfg/home" ] && echo "  ok: isolated home dir created" || { echo "  FAIL: no home dir"; TESTS_FAILED=$((TESTS_FAILED+1)); }; TESTS_RUN=$((TESTS_RUN+1))
  assert_contains "$(cat "$SANDBOX/security.log")" "add-trusted-cert" "cert trusted via security"
  teardown_sandbox
}

test_login_aborts_on_empty_token() {
  setup_sandbox; _stub_login_env
  out="$(printf '\n' | "$CTC_BIN" login 2>&1)"; code=$?
  assert_exit "$code" 1 "empty token aborts"
  assert_contains "$out" "No token" "empty token message"
  [ -f "$HOME/.config/ctc/env" ] && { echo "  FAIL: env written on abort"; TESTS_FAILED=$((TESTS_FAILED+1)); } || echo "  ok: no env on abort"; TESTS_RUN=$((TESTS_RUN+1))
  teardown_sandbox
}

test_login_with_token_flag_is_noninteractive() {
  setup_sandbox; _stub_login_env
  # Redirect stdin from /dev/null: a stray interactive read would EOF-fail fast.
  out="$("$CTC_BIN" login --token github_pat_FLAGTOKEN1234 </dev/null 2>&1)"; code=$?
  assert_exit "$code" 0 "login --token exits 0"
  env="$HOME/.config/ctc/env"
  assert_contains "$(cat "$env" 2>/dev/null || echo '')" "COPILOT_GITHUB_TOKEN=\"github_pat_FLAGTOKEN1234\"" "token written from flag"
  case "$out" in *Paste*) echo "  FAIL: prompted despite --token"; TESTS_FAILED=$((TESTS_FAILED+1));; *) echo "  ok: no prompt";; esac; TESTS_RUN=$((TESTS_RUN+1))
  teardown_sandbox
}

test_install_with_token_auto_logs_in() {
  setup_sandbox; _stub_login_env
  export SHELL=/bin/zsh
  CTC_SRC="$CTC_BIN" sh "$(dirname "$CTC_BIN")/install.sh" -- --token github_pat_INSTALLTOK99 </dev/null >/dev/null 2>&1
  code=$?
  assert_exit "$code" 0 "install --token exits 0"
  env="$HOME/.config/ctc/env"
  assert_contains "$(cat "$env" 2>/dev/null || echo '')" "github_pat_INSTALLTOK99" "install auto-logged-in with token"
  teardown_sandbox
}

test_login_bare_token_flag_aborts_cleanly() {
  setup_sandbox; _stub_login_env
  out="$("$CTC_BIN" login --token </dev/null 2>&1)"; code=$?
  assert_exit "$code" 1 "bare --token aborts"
  assert_contains "$out" "No token" "bare --token shows No token message"
  [ -f "$HOME/.config/ctc/env" ] && { echo "  FAIL: env written on abort"; TESTS_FAILED=$((TESTS_FAILED+1)); } || echo "  ok: no env on abort"; TESTS_RUN=$((TESTS_RUN+1))
  teardown_sandbox
}

test_login_prints_ca_fingerprint() {
  setup_sandbox; _stub_login_env
  out="$(printf 'github_pat_TESTTOKEN1234\n' | "$CTC_BIN" login 2>&1)"; code=$?
  assert_exit "$code" 0 "login exits 0"
  assert_contains "$out" "AA:BB:CC:DD" "fingerprint printed"
  assert_contains "$out" "dashboard" "verify-against-dashboard hint printed"
  teardown_sandbox
}
