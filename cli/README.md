# CTC CLI launcher

Launch GitHub Copilot CLI through the CTC credit proxy without the manual env exports.

## Install (once)
    curl -fsSLk https://<ctc-host>/install.sh | sh

The `-k` is required on first contact: the CTC host uses a self-signed cert that
isn't trusted yet. `ctc login` then trusts it and prints the CA's SHA-256
fingerprint — compare it with the one shown in the dashboard "Set up CLI" panel.

## Set up (once)
    ctc login        # paste the token from the dashboard "Set up CLI" panel; approves one sudo for cert trust and prints the CA fingerprint

## Daily
    ctc              # in an interactive terminal, shows a menu to pick your agent:
                     #   1) GitHub Copilot CLI   2) Claude Code
    ctc copilot      # skip the menu — launch Copilot through CTC directly
    ctc copilot -p "..."   # all copilot flags pass through
    ctc claude       # skip the menu — launch native Claude Code on the Copilot backend
    copilot          # your normal, personal Copilot — untouched, runs side-by-side

The `ctc` menu appears only when stdin/stdout are an interactive TTY. When `ctc`
runs with no args in a non-interactive shell (piped or scripted), it launches
Copilot directly — no prompt — so existing automation is unaffected. Passing any
flags (e.g. `ctc -p "..."`) also skips the menu and goes straight to Copilot.

Other commands: `ctc status`, `ctc logout`.

## Cost readout in Claude Code

`ctc claude` installs a statusline into its **isolated** Claude home
(`~/.config/ctc/home/.claude/`) — never your personal `~/.claude`. It shows what
the session is costing the pool:

    ◆ CTC ▕ Sonnet 5 ▕ ⎇ main ✎ ▕ ⚡ 3.21 AIU · $0.03 (+0.12) ▕ ⑂ 1.04 agents ▕ ⌁ 61k

The cost is priced with **Copilot's own per-model token prices** —
`billing.token_prices` from `GET /models` on `copilot-api`, in nano-AIU per
token, the same table `tools/price_check.py` diffs for price changes. AIU is the
unit the pool is debited in (`docs/reference/metering-contract.md`); the dollar
figure is a display conversion at 1 AIU = $1/110, which is where Copilot's table
lines up with published list prices (sonnet 330 AIU/Mtok in = $3/M, opus 550 =
$5/M, gpt-5-mini 27/220 = $0.25/$2 per M). `(+0.12)` is the last turn.

Everything the session spends is counted, including every agent it spawns.
Claude Code writes agent turns outside the session transcript, nested by kind:

    subagents/agent-*.jsonl                  Task subagents and named teammates
    subagents/workflows/wf_*/agent-*.jsonl   agents inside a Workflow run

The statusline walks all of them and breaks the agent share out as `⑂` — worth
watching, since on a workflow-heavy session the agents can be most of the bill.

Each model is priced at its own rate, so switching models mid-session
gives a correct blended total (earlier turns are never re-priced). A streaming
turn is logged repeatedly under one `requestId` with a growing output count, so
it is charged once at the final size.

This is a **client-side projection, not the ledger.** The authoritative charge is
`copilot_usage.total_nano_aiu`, which only the proxy sees.

### Where the rates come from

`ctc claude` refreshes the price table from Copilot's **live catalog** on launch
— `GET /models` on `copilot-api`, through the CTC proxy like any other call, so
no PAT is needed on the client. That path is read-only and not in
`BILLABLE_PATHS`, so it costs no credit. The result is cached to
`~/.config/ctc/home/.claude/prices.json` and refetched at most once a day.

The fetch runs in the background and swallows every error: an unreachable proxy
delays nothing, breaks no launch, and leaves the cache untouched. The statusline
itself never touches the network — it renders on every keystroke, so it is a
plain disk read with a 7-day staleness guard.

A baked-in table backs all of this up whenever the cache is missing, stale, or
unparseable. It mirrors Copilot's catalog as of **2026-08-18** and covers every
model the picker exposes. Note `claude-sonnet-5` bills at **220/1100** — Copilot
passes through Anthropic's $2/$10 intro rate rather than list $3/$15, so re-check
it after the promo lapses upstream (2026-08-31).

Only `claude-opus-5` is priced without a catalog entry (Copilot doesn't expose
it) — from Anthropic list at the same anchor. It, and anything else unlisted
falling back to its nearest sibling, renders a leading `≈`; the live catalog
clears the flag for every model it confirms.

Set `CTC_AIU_CEILING=<aiu>` to add a burn bar against a known allowance. To
inspect price drift by hand (or refresh the baked-in fallback in `cli/ctc`), run
`PAT=github_pat_xxx python tools/price_check.py`, which diffs the live catalog
against the captured baseline. Needs `python3` on PATH; without it both the
statusline and the price refresh are silently skipped and the launch is
unaffected.

## Use inside VS Code

CTC Copilot runs in VS Code's **integrated terminal** and bridges to the editor
via the Copilot CLI's `/ide` command — editor selection, diagnostics, and
diff-tab approvals, all metered through CTC.

1. Open VS Code's integrated terminal **on your project folder**
   (Terminal → New Terminal).
2. Run `ctc` (after the one-time `ctc login`).
3. Inside Copilot, run `/ide` and pick your workspace.

This is separate from your real Copilot **extension**: the extension keeps using
your own GitHub account, while `ctc` runs Copilot on CTC credits in the same
window (separate processes). Inline ghost-text completions from the native
extension aren't part of this flow — see the Copilot-in-VS-Code design doc for
the planned Phase A.

`/ide` discovers the window through the `~/.copilot/ide` registry. Because `ctc`
isolates `HOME`, the launcher symlinks just that registry into its isolated home
so `/ide` works; everything else (token, session, config) stays isolated. If
`/ide` still says "No active IDE workspaces found", make sure the terminal was
opened *inside* the workspace folder and that "Auto-connect to matching IDE
workspace" is enabled in the `/ide` settings.

macOS only for now. On other systems use the manual setup in TDD.md §6.3.
The launcher never modifies the Copilot CLI or the proxy — it sets the isolating
env (its own HOME under ~/.config/ctc/home) and execs stock `copilot`.

## Tests
    bash cli/tests/run.sh        # unit suite (stubbed, no network)
    CTC_HOST=localhost REAL_TEST_TOKEN=... bash cli/tests/smoke.sh   # real-binary smoke vs a running proxy
