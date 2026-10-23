# CTC CLI launcher

Launch GitHub Copilot CLI through the CTC credit proxy without the manual env exports.

## Install (once)

**macOS:**

    curl -fsSLk https://<ctc-host>/install.sh | sh

The `-k` is required on first contact: the CTC host uses a self-signed cert that
isn't trusted yet. `ctc login` then trusts it and prints the CA's SHA-256
fingerprint — compare it with the one shown in the dashboard "Set up CLI" panel.

**Windows (PowerShell):**

    curl.exe -fsSLko "$env:TEMP\ctc-install.ps1" https://<ctc-host>/install.ps1
    powershell -NoProfile -File "$env:TEMP\ctc-install.ps1" -Token <your-token>

No `sudo`/admin: instead of a password prompt, Windows shows a native "install
certificate?" confirmation dialog for the CA — click yes. The installer never
elevates itself (no `-Verb RunAs`); see [Windows notes](#windows-notes) below.

## Set up (once)
    ctc login        # paste the token from the dashboard "Set up CLI" panel; trusts the CA (sudo on macOS, a confirmation dialog on Windows) and prints the CA fingerprint

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
(`~/.config/ctc/home/.claude/` on macOS, `%APPDATA%\ctc\home\.claude\` on
Windows) — never your personal `~/.claude`. It shows what the session is
costing the pool (paths below are written as the macOS/Unix form; substitute
the Windows path on that platform):

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

### Real charge vs. projection

The transcript tally above is only a **projection**. What the pool is actually
charged is what the proxy booked in its ledger (`consumption_events.credits`,
stored in **nano-AIU**, 1 AIU = 1e9). The statusline shows that figure when it
can:

- Each `ctc claude` launch mints a run tag and sends it on every request as
  `X-CTC-Run-Tag` (via `ANTHROPIC_CUSTOM_HEADERS`, appended to any you set).
  The proxy records it on the ledger row and strips it before forwarding.
- A background poller calls `GET /api/usage?tag=<tag>` every ~10s with your CTC
  token and caches the answer in `~/.config/ctc/home/.claude/ledger/<tag>.json`.
  It exits, and removes the cache, when claude does.
- A cache under 45s old is shown as-is: `⚡ 3.21 AIU`. Otherwise (no cache, poller
  dead, control plane unreachable) the statusline shows the projection, marked
  `⚡ ≈3.21 AIU`. `CTC_LEDGER_POLL=0` turns the poller off.

The scopes differ slightly: the ledger counts this launch, the projection counts
the transcript, which a `--resume`d session carries over from earlier launches.
The `(+last turn)` and `⑂ agents` breakdowns always come from the projection.

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
falling back to its nearest sibling, is priced from the nearest catalog entry
(any projection already renders with a leading `≈`).

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

`/ide` discovers the window through the `~/.copilot/ide` registry (on Windows,
`%USERPROFILE%\.copilot\ide`). Because `ctc` isolates the home directory, the
launcher links just that registry into its isolated home so `/ide` works —
a symlink on macOS, a directory junction on Windows (`New-Item -ItemType
Junction`, no admin/Developer Mode needed) — while everything else (token,
session, config) stays isolated. If `/ide` still says "No active IDE
workspaces found", make sure the terminal was opened *inside* the workspace
folder and that "Auto-connect to matching IDE workspace" is enabled in the
`/ide` settings.

Supported on macOS and Windows (Linux: manual setup, [TDD.md](../TDD.md) §6.3).
The launcher never modifies the Copilot CLI or the proxy — it sets the
isolating env (its own home under `~/.config/ctc/home` on macOS,
`%APPDATA%\ctc\home` on Windows) and runs stock `copilot`.

## Windows notes

- **Paths.** Settings and the isolated Copilot/Claude home live under
  `%APPDATA%\ctc`; the `ctc` command itself installs to
  `%LOCALAPPDATA%\Programs\ctc` (kept off `PATH` as a `.ps1`, exposed as a
  `ctc.cmd` shim instead — PowerShell doesn't run bare `.ps1` files from PATH
  the way a Unix shell runs an executable script).
- **ExecutionPolicy.** If your effective policy is `Restricted` (the Windows
  client default), neither `install.ps1` nor `ctc.ps1` will run — PowerShell
  reports *"running scripts is disabled on this system"*. Fix it once, as your
  own user: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (the
  installer also re-checks and prints this hint). **Never use
  `-ExecutionPolicy Bypass`** — it's exactly the pattern EDR tools flag, and
  this project avoids it everywhere (see `TDD.md`/the plan's EDR assessment).
- **Cert trust.** `ctc login` trusts CTC's CA in `Cert:\CurrentUser\Root` by
  default — no admin needed, just the native Windows confirmation dialog.
  `ctc login -Machine` instead trusts it machine-wide
  (`Cert:\LocalMachine\Root`) — run it yourself from a shell **you've already
  elevated**; the launcher never self-elevates.
- **Statusline.** The Claude Code statusline is a native PowerShell script
  (`statusline.ps1`) — no Python involved on Windows (the macOS version embeds
  Python; the Windows port doesn't need it).
- **Tests.** `pwsh cli/tests/ps/run.ps1` runs the Pester 5 suite locally (not in
  CI) — installs Pester to `CurrentUser` scope first if missing. Windows-only
  cases (cert store, junctions) are tagged `Windows`; the rest also run under
  `pwsh` on macOS/Linux for quick iteration.

## Tests
    bash cli/tests/run.sh        # unit suite (stubbed, no network)
    CTC_HOST=localhost REAL_TEST_TOKEN=... bash cli/tests/smoke.sh   # real-binary smoke vs a running proxy
    pwsh cli/tests/ps/run.ps1    # Windows launcher's Pester 5 suite (run locally)
