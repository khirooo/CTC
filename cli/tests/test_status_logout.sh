test_status_when_not_logged_in() {
  setup_sandbox
  out="$("$CTC_BIN" status 2>&1)"; code=$?
  assert_exit "$code" 0 "status exits 0 when logged out"
  assert_contains "$out" "Not set up" "reports not set up"
  teardown_sandbox
}

test_status_when_logged_in_masks_token() {
  setup_sandbox
  cfg="$HOME/.config/ctc"; mkdir -p "$cfg"
  cat > "$cfg/env" <<EOF
export COPILOT_GITHUB_TOKEN=github_pat_TESTTOKENbeef
export HTTPS_PROXY=http://ctc.local:8080
EOF
  make_stub security 'echo "1 certificate"'    # find-certificate -> trusted
  out="$("$CTC_BIN" status 2>&1)"; code=$?
  assert_exit "$code" 0 "status exits 0"
  assert_contains "$out" "Set up" "reports set up"
  assert_contains "$out" "beef" "shows token tail"
  case "$out" in *TESTTOKEN*) echo "  FAIL: leaked full token"; TESTS_FAILED=$((TESTS_FAILED+1));; *) echo "  ok: full token not shown";; esac; TESTS_RUN=$((TESTS_RUN+1))
  assert_contains "$out" "ctc.local:8080" "shows proxy host"
  teardown_sandbox
}

test_logout_removes_config_only() {
  setup_sandbox
  cfg="$HOME/.config/ctc"; mkdir -p "$cfg/home"
  echo x > "$cfg/env"; echo y > "$HOME/.zshrc"
  "$CTC_BIN" logout >/dev/null 2>&1
  [ -f "$cfg/env" ] && { echo "  FAIL: env not removed"; TESTS_FAILED=$((TESTS_FAILED+1)); } || echo "  ok: env removed"; TESTS_RUN=$((TESTS_RUN+1))
  [ -f "$HOME/.zshrc" ] && echo "  ok: real home untouched" || { echo "  FAIL: touched real home"; TESTS_FAILED=$((TESTS_FAILED+1)); }; TESTS_RUN=$((TESTS_RUN+1))
  teardown_sandbox
}
