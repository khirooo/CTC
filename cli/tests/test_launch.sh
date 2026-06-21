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

test_launch_prints_banner() {
  setup_sandbox
  cfg="$HOME/.config/ctc"; mkdir -p "$cfg/home"
  printf 'export HOME="%s/home"\n' "$cfg" > "$cfg/env"
  make_stub copilot ':'
  out="$("$CTC_BIN" 2>&1)"
  assert_contains "$out" "CTC mode" "prints CTC banner"
  teardown_sandbox
}
