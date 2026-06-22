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
