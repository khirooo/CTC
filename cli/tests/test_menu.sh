# Tests for the interactive agent picker + explicit copilot/claude routing.
# The menu appears ONLY for a bare `ctc` on an interactive TTY. Under the test
# harness stdin/stdout are pipes (no TTY), so bare `ctc` must route straight to
# Copilot without prompting. The menu itself is exercised by sourcing the script
# and calling cmd_menu directly with a piped choice.

# Writes cfg/env so cmd_copilot / cmd_claude pass their "not set up" guard.
_menu_setup_env() {
  cfg="$HOME/.config/ctc"; mkdir -p "$cfg/home"
  cat > "$cfg/env" <<EOF
export HOME="$cfg/home"
export GH_HOST=example.ghe.com
export COPILOT_GITHUB_TOKEN=github_pat_TESTTOKEN1234
export HTTPS_PROXY=http://ctc.local:8080
EOF
}

test_bare_ctc_without_tty_routes_to_copilot_no_menu() {
  setup_sandbox
  _menu_setup_env
  make_stub copilot 'echo "ran" > "$HOME/copilot_out"'
  make_stub claude ':'
  # stdin/stdout are pipes here -> [ -t 0 ] && [ -t 1 ] is false -> no menu.
  out="$("$CTC_BIN" 2>&1)"; code=$?
  assert_exit "$code" 0 "bare ctc (no TTY) exits 0"
  assert_contains "$(cat "$cfg/home/copilot_out" 2>/dev/null)" "ran" \
    "bare ctc without a TTY launches Copilot"
  TESTS_RUN=$((TESTS_RUN+1))
  case "$out" in
    *"choose your agent"*) echo "  FAIL: menu shown without a TTY"; TESTS_FAILED=$((TESTS_FAILED+1));;
    *) echo "  ok: no menu shown without a TTY";;
  esac
  assert_exit "$([ -f "$SANDBOX/claude.log" ] && echo 1 || echo 0)" 0 \
    "claude was NOT launched by bare ctc"
  teardown_sandbox
}

test_copilot_subcommand_passes_flags_through() {
  setup_sandbox
  _menu_setup_env
  make_stub copilot 'echo "ARGS=$*" > "$HOME/copilot_out"'
  out="$("$CTC_BIN" copilot -p "hello world" 2>/dev/null)"; code=$?
  assert_exit "$code" 0 "ctc copilot exits 0"
  assert_contains "$(cat "$cfg/home/copilot_out" 2>/dev/null)" "ARGS=-p hello world" \
    "ctc copilot passes flags through to Copilot"
  teardown_sandbox
}

test_claude_subcommand_bypasses_menu() {
  setup_sandbox
  _menu_setup_env
  make_stub claude 'echo "MODEL=$ANTHROPIC_MODEL ARGS=$*" > "$HOME/claude_out"'
  out="$("$CTC_BIN" claude -p "hi" 2>&1)"; code=$?
  assert_exit "$code" 0 "ctc claude exits 0"
  assert_contains "$(cat "$cfg/home/claude_out" 2>/dev/null)" "ARGS=-p hi" \
    "ctc claude launches Claude Code with args"
  TESTS_RUN=$((TESTS_RUN+1))
  case "$out" in
    *"choose your agent"*) echo "  FAIL: menu shown for explicit 'ctc claude'"; TESTS_FAILED=$((TESTS_FAILED+1));;
    *) echo "  ok: 'ctc claude' bypasses the menu";;
  esac
  teardown_sandbox
}

# Sourced-function tests for the picker itself. Sourcing ctc defines the cmd_*
# functions without running main (source guard), so we can drive cmd_menu with a
# scripted choice on stdin. cmd_copilot / cmd_claude exec the stub and replace
# the subshell, so each runs in its own ( ).
test_menu_choice_1_launches_copilot() {
  setup_sandbox
  _menu_setup_env
  make_stub copilot 'echo "ran" > "$HOME/copilot_out"'
  make_stub claude 'echo "ran" > "$HOME/claude_out"'
  printf '1\n' | ( . "$CTC_BIN"; cmd_menu ) >/dev/null 2>&1
  assert_contains "$(cat "$cfg/home/copilot_out" 2>/dev/null)" "ran" \
    "menu choice 1 launches Copilot"
  assert_exit "$([ -f "$cfg/home/claude_out" ] && echo 1 || echo 0)" 0 \
    "menu choice 1 does NOT launch Claude"
  teardown_sandbox
}

test_menu_choice_2_launches_claude() {
  setup_sandbox
  _menu_setup_env
  make_stub copilot 'echo "ran" > "$HOME/copilot_out"'
  make_stub claude 'echo "ran" > "$HOME/claude_out"'
  printf '2\n' | ( . "$CTC_BIN"; cmd_menu ) >/dev/null 2>&1
  assert_contains "$(cat "$cfg/home/claude_out" 2>/dev/null)" "ran" \
    "menu choice 2 launches Claude"
  assert_exit "$([ -f "$cfg/home/copilot_out" ] && echo 1 || echo 0)" 0 \
    "menu choice 2 does NOT launch Copilot"
  teardown_sandbox
}

test_menu_reprompts_on_invalid_then_launches() {
  setup_sandbox
  _menu_setup_env
  make_stub copilot 'echo "ran" > "$HOME/copilot_out"'
  # First line is garbage (re-prompt), second selects Copilot.
  out="$(printf 'x\n1\n' | ( . "$CTC_BIN"; cmd_menu ) 2>&1)"
  assert_contains "$out" "Please enter 1 or 2" "invalid input re-prompts"
  assert_contains "$(cat "$cfg/home/copilot_out" 2>/dev/null)" "ran" \
    "menu proceeds after a re-prompt"
  teardown_sandbox
}

test_menu_eof_exits_clean() {
  setup_sandbox
  _menu_setup_env
  make_stub copilot ':'
  make_stub claude ':'
  # Empty stdin -> immediate EOF -> exit 0, nothing launched.
  printf '' | ( . "$CTC_BIN"; cmd_menu ) >/dev/null 2>&1; code=$?
  assert_exit "$code" 0 "EOF exits the menu cleanly (0)"
  teardown_sandbox
}

test_claude_banner_shows_model_flag_over_default() {
  setup_sandbox
  _menu_setup_env
  make_stub claude ':'
  out="$("$CTC_BIN" claude 2>&1)"
  assert_contains "$out" "model: claude-sonnet-5 " "banner shows the default model without --model"
  out="$("$CTC_BIN" claude -p hi --model claude-opus-5.5 2>&1)"
  assert_contains "$out" "model: claude-opus-5.5 " "banner shows --model X"
  out="$("$CTC_BIN" claude --model=claude-haiku-4.5 2>&1)"
  assert_contains "$out" "model: claude-haiku-4.5 " "banner shows --model=X"
  teardown_sandbox
}
