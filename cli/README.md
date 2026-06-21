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

macOS only for now. On other systems use the manual setup in TDD.md §6.3.
The launcher never modifies the Copilot CLI or the proxy — it sets the isolating
env (its own HOME under ~/.config/ctc/home) and execs stock `copilot`.

## Tests
    bash cli/tests/run.sh        # unit suite (stubbed, no network)
    CTC_HOST=localhost REAL_TEST_TOKEN=... bash cli/tests/smoke.sh   # real-binary smoke vs a running proxy
