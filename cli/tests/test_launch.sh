test_launch_without_config_prompts_login() {
  setup_sandbox
  out="$("$CTC_BIN" 2>&1)"; code=$?
  assert_exit "$code" 1 "no config exits 1"
  assert_contains "$out" "ctc login" "tells user to log in first"
  teardown_sandbox
}

test_launch_execs_copilot_with_isolated_env() {
  setup_sandbox
  cfg="$HOME/.config/ctc"; mkdir -p "$cfg/home"
  cat > "$cfg/env" <<EOF
export HOME="$cfg/home"
export GH_HOST=example.ghe.com
export COPILOT_GITHUB_TOKEN=github_pat_TESTTOKEN1234
export HTTPS_PROXY=http://ctc.local:8080
EOF
  # copilot stub records the env + args it was exec'd with, into the *isolated* HOME
  # (the sourced env sets HOME=$cfg/home, so the stub writes there).
  make_stub copilot 'echo "HOME=$HOME GH=$GH_HOST PROXY=$HTTPS_PROXY ARGS=$*" > "$HOME/copilot_out"'
  out="$("$CTC_BIN" -p "hello world" 2>/dev/null)"; code=$?
  assert_exit "$code" 0 "launch exits 0"
  rec="$(cat "$cfg/home/copilot_out")"
  assert_contains "$rec" "HOME=$cfg/home" "copilot ran with isolated HOME"
  assert_contains "$rec" "GH=example.ghe.com" "copilot ran with GH_HOST"
  assert_contains "$rec" "PROXY=http://ctc.local:8080" "copilot ran behind proxy"
  assert_contains "$rec" "ARGS=-p hello world" "args passed through"
  teardown_sandbox
}

test_launch_bridges_ide_discovery_path_into_isolated_home() {
  setup_sandbox
  # The sandbox's $HOME is the *real* home here; VS Code registers the live
  # workspace under ~/.copilot/ide, which the isolated copilot must be able to see.
  real_home="$HOME"
  disc=".copilot/ide"
  mkdir -p "$real_home/$disc"
  echo "workspace-marker" > "$real_home/$disc/registry.json"

  cfg="$real_home/.config/ctc"; mkdir -p "$cfg/home"
  cat > "$cfg/env" <<EOF
export HOME="$cfg/home"
export GH_HOST=example.ghe.com
export COPILOT_GITHUB_TOKEN=github_pat_TESTTOKEN1234
export HTTPS_PROXY=http://ctc.local:8080
EOF
  make_stub copilot ':'

  "$CTC_BIN" >/dev/null 2>&1; code=$?
  assert_exit "$code" 0 "launch exits 0"
  bridged="$cfg/home/$disc/registry.json"
  assert_contains "$(cat "$bridged" 2>/dev/null)" "workspace-marker" \
    "isolated HOME sees the real ~/.copilot/ide registry"
  teardown_sandbox
}

test_launch_bridges_even_when_stale_empty_ide_dir_exists() {
  setup_sandbox
  # Regression: an earlier ctc run left an empty .copilot/ide in the isolated
  # home. The bridge must replace it so the real registry shows through.
  real_home="$HOME"
  mkdir -p "$real_home/.copilot/ide"
  echo "live-lock" > "$real_home/.copilot/ide/conn.lock"
  cfg="$real_home/.config/ctc"; mkdir -p "$cfg/home/.copilot/ide"   # stale empty isolated ide
  printf 'export HOME="%s/home"\n' "$cfg" > "$cfg/env"
  make_stub copilot ':'

  "$CTC_BIN" >/dev/null 2>&1
  assert_contains "$(cat "$cfg/home/.copilot/ide/conn.lock" 2>/dev/null)" "live-lock" \
    "stale empty isolated ide is replaced so the real registry shows through"
  teardown_sandbox
}

test_launch_does_not_share_rest_of_copilot_dir() {
  setup_sandbox
  real_home="$HOME"
  mkdir -p "$real_home/.copilot/ide"
  echo "real-token" > "$real_home/.copilot/config.json"   # must stay private to real home

  cfg="$real_home/.config/ctc"; mkdir -p "$cfg/home"
  printf 'export HOME="%s/home"\n' "$cfg" > "$cfg/env"
  make_stub copilot ':'

  "$CTC_BIN" >/dev/null 2>&1
  # Only .copilot/ide is bridged; config.json is NOT visible from the isolated home.
  assert_exit "$([ -e "$cfg/home/.copilot/config.json" ] && echo 1 || echo 0)" 0 \
    "isolated HOME does NOT see real ~/.copilot/config.json"
  teardown_sandbox
}

test_launch_without_discovery_dir_still_runs() {
  setup_sandbox
  cfg="$HOME/.config/ctc"; mkdir -p "$cfg/home"
  printf 'export HOME="%s/home"\n' "$cfg" > "$cfg/env"
  make_stub copilot ':'
  out="$("$CTC_BIN" 2>&1)"; code=$?
  assert_exit "$code" 0 "launch with no discovery dir still exits 0"
  assert_contains "$out" "CTC mode" "still prints banner"
  teardown_sandbox
}

test_launch_prints_banner() {
  setup_sandbox
  cfg="$HOME/.config/ctc"; mkdir -p "$cfg/home"
  printf 'export HOME="%s/home"\n' "$cfg" > "$cfg/env"
  make_stub copilot ':'
  out="$("$CTC_BIN" 2>&1)"
  assert_contains "$out" "CTC mode" "prints CTC banner"
  teardown_sandbox
}

# Writes a minimal login env and a copilot stub that records NO_PROXY/no_proxy.
_no_proxy_fixture() {
  cfg="$HOME/.config/ctc"; mkdir -p "$cfg/home"
  printf 'export HOME="%s/home"\nexport HTTPS_PROXY=http://ctc.local:8080\n' "$cfg" > "$cfg/env"
  make_stub copilot 'echo "NP=${NO_PROXY:-} np=${no_proxy:-}" > "$HOME/copilot_out"'
}

test_launch_exports_ctc_no_proxy_hosts() {
  setup_sandbox; _no_proxy_fixture
  CTC_NO_PROXY=jira.corp.example,corp.example NO_PROXY= no_proxy= "$CTC_BIN" >/dev/null 2>&1
  rec="$(cat "$cfg/home/copilot_out")"
  assert_contains "$rec" "NP=jira.corp.example,corp.example " "NO_PROXY carries CTC_NO_PROXY"
  assert_contains "$rec" "np=jira.corp.example,corp.example" "no_proxy mirrors it (curl/Go read lowercase)"
  teardown_sandbox
}

test_launch_keeps_users_existing_no_proxy() {
  setup_sandbox; _no_proxy_fixture
  CTC_NO_PROXY=jira.corp.example NO_PROXY=localhost,127.0.0.1 "$CTC_BIN" >/dev/null 2>&1
  assert_contains "$(cat "$cfg/home/copilot_out")" "NP=localhost,127.0.0.1,jira.corp.example " \
    "existing NO_PROXY is kept and extended, not replaced"
  teardown_sandbox
}

test_launch_leaves_no_proxy_alone_when_unset() {
  setup_sandbox; _no_proxy_fixture
  CTC_NO_PROXY= NO_PROXY=localhost no_proxy= "$CTC_BIN" >/dev/null 2>&1
  assert_contains "$(cat "$cfg/home/copilot_out")" "NP=localhost np=" "no CTC_NO_PROXY → env untouched"
  teardown_sandbox
}

test_no_proxy_build_time_rewrite_bakes_default() {
  # Mirrors the sed in web/Dockerfile: the served launcher must carry the list
  # as its default, so teammates get it without setting anything.
  setup_sandbox
  baked="$SANDBOX/ctc"; cp "$CTC_BIN" "$baked"
  sed -i.bak "s/CTC_NO_PROXY:-}/CTC_NO_PROXY:-jira.corp.example}/g" "$baked"
  assert_contains "$(grep -c 'CTC_NO_PROXY:-jira.corp.example}' "$baked")" "1" "sed anchor matches exactly once"
  _no_proxy_fixture
  env -u CTC_NO_PROXY NO_PROXY= no_proxy= bash "$baked" >/dev/null 2>&1
  assert_contains "$(cat "$cfg/home/copilot_out")" "NP=jira.corp.example " "baked default reaches the agent"
  teardown_sandbox
}

# Login env + a curl stub that "serves" $SANDBOX/served as /ctc at the -o target.
_update_fixture() {
  cfg="$HOME/.config/ctc"; mkdir -p "$cfg/home"
  printf 'export HOME="%s/home"\n' "$cfg" > "$cfg/env"
  make_stub copilot ':'
  make_stub curl 'prev=""; for a in "$@"; do if [ "$prev" = "-o" ]; then cat "'"$SANDBOX"'/served" > "$a"; fi; prev="$a"; done'
}

# The verdict is written by a background job; wait for it (bounded).
_wait_for_verdict() {
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    [ -f "$cfg/launcher-check" ] && return 0; sleep 0.25
  done
}

test_update_check_quiet_when_launcher_matches_server() {
  setup_sandbox; _update_fixture
  cp "$CTC_BIN" "$SANDBOX/served"
  CTC_UPDATE_CHECK=1 "$CTC_BIN" >/dev/null 2>&1; _wait_for_verdict
  assert_contains "$(sed -n 2p "$cfg/launcher-check")" "ok" "identical served launcher recorded as ok"
  out="$(CTC_UPDATE_CHECK=1 "$CTC_BIN" 2>&1)"
  TESTS_RUN=$((TESTS_RUN+1))
  case "$out" in
    *"out of date"*) echo "  FAIL: up-to-date launcher warned"; TESTS_FAILED=$((TESTS_FAILED+1));;
    *) echo "  ok: no warning when the launcher matches the server";;
  esac
  teardown_sandbox
}

test_update_check_warns_on_next_launch_when_server_differs() {
  setup_sandbox; _update_fixture
  { cat "$CTC_BIN"; echo "# newer"; } > "$SANDBOX/served"
  CTC_UPDATE_CHECK=1 "$CTC_BIN" >/dev/null 2>&1; _wait_for_verdict
  assert_contains "$(sed -n 2p "$cfg/launcher-check")" "stale" "differing served launcher recorded as stale"
  out="$(CTC_UPDATE_CHECK=1 "$CTC_BIN" 2>&1)"
  assert_contains "$out" "out of date" "next launch warns the launcher is stale"
  assert_contains "$out" "/install.sh | sh" "warning says how to update"
  teardown_sandbox
}

test_update_check_fetches_at_most_once_a_day() {
  setup_sandbox; _update_fixture
  cp "$CTC_BIN" "$SANDBOX/served"
  printf '%s\nok\n' "$(date +%s)" > "$cfg/launcher-check"
  CTC_UPDATE_CHECK=1 "$CTC_BIN" >/dev/null 2>&1; sleep 0.5
  assert_exit "$([ -f "$SANDBOX/curl.log" ] && echo 1 || echo 0)" 0 "fresh verdict -> no fetch"
  teardown_sandbox
}

test_update_check_failed_fetch_records_nothing() {
  setup_sandbox; _update_fixture
  make_stub curl 'exit 7'
  CTC_UPDATE_CHECK=1 "$CTC_BIN" >/dev/null 2>&1; code=$?; sleep 0.5
  assert_exit "$code" 0 "launch still succeeds when the web host is unreachable"
  assert_exit "$([ -f "$cfg/launcher-check" ] && echo 1 || echo 0)" 0 "no verdict recorded on a failed fetch"
  teardown_sandbox
}
