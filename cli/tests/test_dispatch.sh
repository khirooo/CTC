test_unknown_subcommand_shows_usage() {
  setup_sandbox
  out="$("$CTC_BIN" bogus 2>&1)"; code=$?
  assert_exit "$code" 2 "unknown subcommand exits 2"
  assert_contains "$out" "Usage:" "unknown subcommand prints usage"
  teardown_sandbox
}

test_help_flag_shows_usage() {
  setup_sandbox
  out="$("$CTC_BIN" --help 2>&1)"; code=$?
  assert_exit "$code" 0 "--help exits 0"
  assert_contains "$out" "ctc login" "usage lists login"
  teardown_sandbox
}
