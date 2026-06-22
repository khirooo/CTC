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
    ctc              # launches Copilot through CTC; all copilot flags pass through, e.g. ctc -p "..."
    copilot          # your normal, personal Copilot — untouched, runs side-by-side

Other commands: `ctc status`, `ctc logout`.

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
