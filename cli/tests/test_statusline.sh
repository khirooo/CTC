# Tests for the CTC statusline installed into the isolated Claude HOME by
# `ctc claude`. It must land in the ISOLATED home only (never the user's real
# ~/.claude), merge into any existing settings.json, and price a transcript with
# Copilot's own per-model token prices.

_sl_setup_env() {
  cfg="$HOME/.config/ctc"; mkdir -p "$cfg/home"
  cat > "$cfg/env" <<EOF
export HOME="$cfg/home"
export GH_HOST=example.ghe.com
export COPILOT_GITHUB_TOKEN=github_pat_TESTTOKEN1234
export HTTPS_PROXY=http://ctc.local:8080
EOF
}

test_statusline_installed_into_isolated_home_only() {
  setup_sandbox
  real_home="$HOME"
  _sl_setup_env
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1
  assert_exit "$([ -f "$cfg/home/.claude/statusline.py" ] && echo 0 || echo 1)" 0 \
    "statusline.py written into the isolated HOME"
  assert_contains "$(cat "$cfg/home/.claude/settings.json" 2>/dev/null)" "statusLine" \
    "statusLine configured in the isolated settings.json"
  assert_exit "$([ -e "$real_home/.claude" ] && echo 1 || echo 0)" 0 \
    "the user's real ~/.claude is never created or touched"
  teardown_sandbox
}

test_statusline_merges_into_existing_settings() {
  setup_sandbox
  _sl_setup_env
  mkdir -p "$cfg/home/.claude"
  echo '{"model":"claude-sonnet-5"}' > "$cfg/home/.claude/settings.json"
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1
  got="$(cat "$cfg/home/.claude/settings.json")"
  assert_contains "$got" "claude-sonnet-5" "pre-existing settings keys survive"
  assert_contains "$got" "statusline.py" "statusLine command points at the script"
  teardown_sandbox
}

test_statusline_prices_transcript_with_copilot_rates() {
  setup_sandbox
  _sl_setup_env
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1

  # One assistant turn on claude-sonnet-4.6 — Copilot's listed rates are
  # 330/1650/33/412 nano-AIU per token (x1000). Use only 5m cache writes so the
  # expected value is a plain table lookup:
  #   1000*330000 + 500*1650000 + 2000*33000 + 100*412500 = 1_262_250_000 nano
  #   = 1.26 AIU  -> $0.01 at 1 AIU = $1/110
  t="$SANDBOX/transcript.jsonl"
  cat > "$t" <<'EOF'
{"type":"assistant","requestId":"r1","message":{"model":"claude-sonnet-4.6","usage":{"input_tokens":1000,"output_tokens":500,"cache_read_input_tokens":2000,"cache_creation_input_tokens":100,"cache_creation":{"ephemeral_5m_input_tokens":100,"ephemeral_1h_input_tokens":0}}}}
EOF
  out="$(printf '{"model":{"display_name":"Sonnet 5","id":"claude-sonnet-5"},"workspace":{"current_dir":"%s","project_dir":"%s"},"session_id":"s1","transcript_path":"%s"}' \
        "$SANDBOX" "$SANDBOX" "$t" | HOME="$cfg/home" python3 "$cfg/home/.claude/statusline.py" 2>&1)"
  assert_contains "$out" "1.26 AIU" "session cost priced at Copilot's sonnet rates"
  assert_contains "$out" '$0.01' "AIU converted to USD at 1 AIU = \$1/110"
  assert_contains "$out" "CTC" "statusline is branded as the CTC session"
  assert_contains "$out" "Sonnet 5" "model name shown"
  teardown_sandbox
}

test_statusline_marks_unlisted_models_as_approximate() {
  setup_sandbox
  _sl_setup_env
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1

  # claude-opus-6 is not in Copilot's catalog -> priced off the nearest listed
  # sibling (claude-opus-4.7) and flagged with a leading "≈".
  t="$SANDBOX/transcript.jsonl"
  cat > "$t" <<'EOF'
{"type":"assistant","requestId":"r1","message":{"model":"claude-opus-6","usage":{"input_tokens":1000,"output_tokens":1000,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
EOF
  out="$(printf '{"model":{"display_name":"Opus 6"},"workspace":{"current_dir":"%s"},"session_id":"s2","transcript_path":"%s"}' \
        "$SANDBOX" "$t" | HOME="$cfg/home" python3 "$cfg/home/.claude/statusline.py" 2>&1)"
  # 1000*550000 + 1000*2750000 = 3_300_000_000 nano = 3.30 AIU
  assert_contains "$out" "3.30 AIU" "unlisted opus priced off the nearest listed opus"
  assert_contains "$out" "≈" "approximate pricing is flagged"
  teardown_sandbox
}

test_statusline_survives_missing_transcript_and_junk_input() {
  setup_sandbox
  _sl_setup_env
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1
  out="$(printf 'not json at all' | HOME="$cfg/home" python3 "$cfg/home/.claude/statusline.py" 2>&1)"; code=$?
  assert_exit "$code" 0 "statusline exits 0 on junk stdin"
  assert_contains "$out" "CTC" "still renders a line"
  teardown_sandbox
}

test_statusline_counts_subagent_transcripts() {
  setup_sandbox
  _sl_setup_env
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1

  # Subagent turns are NOT in the session transcript — Claude Code writes them
  # to <project>/<session-id>/subagents/agent-*.jsonl. They cost real credit, so
  # the pool figure must include them.
  t="$SANDBOX/proj/sess.jsonl"; mkdir -p "$SANDBOX/proj/sess/subagents"
  cat > "$t" <<'EOF'
{"type":"assistant","requestId":"m1","message":{"model":"claude-sonnet-4.6","usage":{"input_tokens":1000,"output_tokens":1000}}}
EOF
  cat > "$SANDBOX/proj/sess/subagents/agent-a1.jsonl" <<'EOF'
{"type":"assistant","isSidechain":true,"requestId":"a1","message":{"model":"claude-sonnet-4.6","usage":{"input_tokens":1000,"output_tokens":1000}}}
EOF
  out="$(printf '{"model":{"display_name":"Sonnet 5"},"workspace":{"current_dir":"%s"},"session_id":"sess","transcript_path":"%s"}' \
        "$SANDBOX" "$t" | HOME="$cfg/home" python3 "$cfg/home/.claude/statusline.py" 2>&1)"
  # main 1.98 + agent 1.98 = 3.96 AIU
  assert_contains "$out" "3.96 AIU" "subagent cost is included in the session total"
  assert_contains "$out" "1.98" "subagent share is broken out separately"
  assert_contains "$out" "agents" "subagent share is labelled"
  teardown_sandbox
}

test_statusline_dedupes_streaming_partials_by_max() {
  setup_sandbox
  _sl_setup_env
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1

  # One streaming turn is logged repeatedly under a single requestId with a
  # GROWING output count. Charge it once, at the final (largest) value —
  # first-wins would undercount, sum-all would triple-count.
  t="$SANDBOX/t.jsonl"
  cat > "$t" <<'EOF'
{"type":"assistant","requestId":"r1","message":{"model":"claude-sonnet-4.6","usage":{"input_tokens":1000,"output_tokens":5}}}
{"type":"assistant","requestId":"r1","message":{"model":"claude-sonnet-4.6","usage":{"input_tokens":1000,"output_tokens":400}}}
{"type":"assistant","requestId":"r1","message":{"model":"claude-sonnet-4.6","usage":{"input_tokens":1000,"output_tokens":1000}}}
{"type":"assistant","requestId":"r1","message":{"model":"claude-sonnet-4.6","usage":{"input_tokens":1000,"output_tokens":1000}}}
EOF
  out="$(printf '{"model":{"display_name":"Sonnet 5"},"workspace":{"current_dir":"%s"},"session_id":"s3","transcript_path":"%s"}' \
        "$SANDBOX" "$t" | HOME="$cfg/home" python3 "$cfg/home/.claude/statusline.py" 2>&1)"
  assert_contains "$out" "1.98 AIU" "streaming partials charged once at the final size"
  teardown_sandbox
}

test_statusline_ignores_synthetic_messages() {
  setup_sandbox
  _sl_setup_env
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1

  # "<synthetic>" is a local/error message, never billed — it must cost 0 AND
  # not flag the session as approximately priced.
  t="$SANDBOX/t.jsonl"
  cat > "$t" <<'EOF'
{"type":"assistant","requestId":"r1","message":{"model":"claude-sonnet-4.6","usage":{"input_tokens":1000,"output_tokens":1000}}}
{"type":"assistant","requestId":"r2","message":{"model":"<synthetic>","usage":{"input_tokens":0,"output_tokens":0}}}
EOF
  out="$(printf '{"model":{"display_name":"Sonnet 5"},"workspace":{"current_dir":"%s"},"session_id":"s4","transcript_path":"%s"}' \
        "$SANDBOX" "$t" | HOME="$cfg/home" python3 "$cfg/home/.claude/statusline.py" 2>&1)"
  assert_contains "$out" "1.98 AIU" "synthetic messages add no cost"
  case "$out" in
    *"≈"*) echo "  FAIL: synthetic message wrongly flagged the session approximate"; TESTS_FAILED=$((TESTS_FAILED+1));;
    *) echo "  ok: synthetic message does not flag the session approximate";;
  esac
  TESTS_RUN=$((TESTS_RUN+1))
  teardown_sandbox
}

test_statusline_counts_nested_teammate_and_workflow_agents() {
  setup_sandbox
  _sl_setup_env
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1

  # Agent transcripts nest by kind under subagents/:
  #   agent-*.jsonl                  Task subagents and named teammates
  #   workflows/wf_*/agent-*.jsonl   agents inside a Workflow run
  # All bill the pool, so the walk must recurse.
  t="$SANDBOX/p/sess.jsonl"
  mkdir -p "$SANDBOX/p/sess/subagents/workflows/wf_abc" "$SANDBOX/p/sess/subagents/workflows/wf_def"
  turn() { printf '{"type":"assistant","requestId":"%s","message":{"model":"claude-sonnet-4.6","usage":{"input_tokens":1000,"output_tokens":1000}}}\n' "$1"; }
  turn m1 > "$t"
  turn t1 > "$SANDBOX/p/sess/subagents/agent-adashboard-builder-1.jsonl"   # named teammate
  turn w1 > "$SANDBOX/p/sess/subagents/workflows/wf_abc/agent-a1.jsonl"    # workflow agent
  turn w2 > "$SANDBOX/p/sess/subagents/workflows/wf_def/agent-a2.jsonl"    # another wf run
  # same bare filename in two workflow dirs must not collide in the offset cache
  turn j1 > "$SANDBOX/p/sess/subagents/workflows/wf_abc/journal.jsonl"
  turn j2 > "$SANDBOX/p/sess/subagents/workflows/wf_def/journal.jsonl"

  out="$(printf '{"model":{"display_name":"Sonnet 5"},"workspace":{"current_dir":"%s"},"session_id":"sess","transcript_path":"%s"}' \
        "$SANDBOX" "$t" | HOME="$cfg/home" python3 "$cfg/home/.claude/statusline.py" 2>&1)"
  # 6 turns x 1.98 = 11.88 total, of which 5 x 1.98 = 9.90 is agents
  assert_contains "$out" "11.88 AIU" "teammate + workflow agents all counted"
  assert_contains "$out" "9.90" "agent share covers nested workflow runs"

  # second render must be a no-op (incremental cache must not double-count)
  out2="$(printf '{"model":{"display_name":"Sonnet 5"},"workspace":{"current_dir":"%s"},"session_id":"sess","transcript_path":"%s"}' \
        "$SANDBOX" "$t" | HOME="$cfg/home" python3 "$cfg/home/.claude/statusline.py" 2>&1)"
  assert_contains "$out2" "11.88 AIU" "re-render does not double-count"
  teardown_sandbox
}

# ---- live price table (fetched from Copilot's catalog by `ctc claude`) ----

test_statusline_prefers_live_price_cache() {
  setup_sandbox
  _sl_setup_env
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1

  # A live catalog entry overrides the baked-in table AND counts as exact, so
  # the "≈" (priced from list, not from Copilot) disappears.
  python3 - "$cfg/home/.claude/prices.json" <<'PY'
import json, sys, time
json.dump({"fetched": int(time.time()), "source": "test",
           "prices": {"claude-sonnet-5": [400, 2000, 40, 500]}}, open(sys.argv[1], "w"))
PY
  t="$SANDBOX/t.jsonl"
  cat > "$t" <<'EOF'
{"type":"assistant","requestId":"r1","message":{"model":"claude-sonnet-5","usage":{"input_tokens":1000,"output_tokens":1000}}}
EOF
  out="$(printf '{"model":{"display_name":"Sonnet 5"},"workspace":{"current_dir":"%s"},"session_id":"L1","transcript_path":"%s"}' \
        "$SANDBOX" "$t" | HOME="$cfg/home" python3 "$cfg/home/.claude/statusline.py" 2>&1)"
  # live rates: 1000*400000 + 1000*2000000 = 2.40 AIU (baked-in sonnet-5 is 1.32)
  assert_contains "$out" "2.40 AIU" "live catalog price wins over the baked-in table"
  case "$out" in
    *"≈"*) echo "  FAIL: catalog-confirmed model still flagged approximate"; TESTS_FAILED=$((TESTS_FAILED+1));;
    *) echo "  ok: catalog-confirmed model is no longer flagged approximate";;
  esac
  TESTS_RUN=$((TESTS_RUN+1))
  teardown_sandbox
}

test_statusline_ignores_stale_or_corrupt_price_cache() {
  setup_sandbox
  _sl_setup_env
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1
  t="$SANDBOX/t.jsonl"
  cat > "$t" <<'EOF'
{"type":"assistant","requestId":"r1","message":{"model":"claude-sonnet-5","usage":{"input_tokens":1000,"output_tokens":1000}}}
EOF
  render() { printf '{"model":{"display_name":"Sonnet 5"},"workspace":{"current_dir":"%s"},"session_id":"%s","transcript_path":"%s"}' \
        "$SANDBOX" "$1" "$t" | HOME="$cfg/home" python3 "$cfg/home/.claude/statusline.py" 2>&1; }

  # older than the 7-day TTL -> ignored, baked-in table used
  python3 - "$cfg/home/.claude/prices.json" <<'PY'
import json, sys, time
json.dump({"fetched": int(time.time()) - 30 * 86400,
           "prices": {"claude-sonnet-5": [400, 2000, 40, 500]}}, open(sys.argv[1], "w"))
PY
  assert_contains "$(render S1)" "1.32 AIU" "stale price cache is ignored"

  echo 'not json {{{' > "$cfg/home/.claude/prices.json"
  assert_contains "$(render S2)" "1.32 AIU" "corrupt price cache falls back to the baked-in table"
  teardown_sandbox
}

test_price_refresh_never_blocks_or_breaks_launch() {
  setup_sandbox
  _sl_setup_env
  # point the proxy at a black-holed port: the fetch must fail silently in the
  # background, leave no bogus cache, and never delay or fail the launch.
  echo 'export HTTPS_PROXY=http://127.0.0.1:9' >> "$cfg/env"
  make_stub claude 'echo ran > "$HOME/claude_out"'
  start=$(date +%s)
  "$CTC_BIN" claude >/dev/null 2>&1; code=$?
  elapsed=$(( $(date +%s) - start ))
  assert_exit "$code" 0 "launch exits 0 with an unreachable proxy"
  assert_contains "$(cat "$cfg/home/claude_out" 2>/dev/null)" "ran" "claude still launched"
  assert_exit "$([ "$elapsed" -lt 10 ] && echo 0 || echo 1)" 0 "launch is not blocked by the price fetch"
  assert_exit "$([ -f "$cfg/home/.claude/prices.json" ] && echo 1 || echo 0)" 0 \
    "no bogus price cache written when the fetch fails"
  teardown_sandbox
}

test_statusline_does_not_price_gemini_as_a_gpt_mini() {
  setup_sandbox
  _sl_setup_env
  make_stub claude ':'
  "$CTC_BIN" claude >/dev/null 2>&1

  # "gemini" CONTAINS the substring "mini". An unlisted Gemini id must fall back
  # to the Gemini family (165/990), not to gpt-5.4-mini (82/495).
  t="$SANDBOX/t.jsonl"
  cat > "$t" <<'EOF'
{"type":"assistant","requestId":"r1","message":{"model":"gemini-9.9-experimental","usage":{"input_tokens":1000,"output_tokens":1000}}}
EOF
  out="$(printf '{"model":{"display_name":"Gemini"},"workspace":{"current_dir":"%s"},"session_id":"G1","transcript_path":"%s"}' \
        "$SANDBOX" "$t" | HOME="$cfg/home" python3 "$cfg/home/.claude/statusline.py" 2>&1)"
  # gemini rates: 1000*165000 + 1000*990000 = 1.155 -> 1.16 AIU (a mini would be 0.58)
  assert_contains "$out" "1.16 AIU" "unlisted Gemini falls back to Gemini, not to a GPT mini"
  teardown_sandbox
}
