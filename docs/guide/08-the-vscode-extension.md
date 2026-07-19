# 08 — The VS Code extension

Routes the **GitHub Copilot Chat extension** through CTC, so IDE chat bills the
shared pool instead of the user's own seat. It's the IDE counterpart to the `ctc`
CLI launcher (guide 02).

## How it works

Unlike the CLI (which runs Copilot in an isolated subprocess), a VS Code extension
can't sandbox the official Copilot extension — they share one window and one
`http.proxy`. So the CTC extension is a **toggle**, not a wrapper:

- Clicking `◆ CTC` (status bar) points VS Code's `http.proxy` at a **local identity
  shim**, sets `proxyStrictSSL:false` / `proxySupport:on`, clears the
  `github.copilot.advanced.authProvider:"github-enterprise"` conflict, starts the
  shim, and reloads. Toggling off restores everything.
- The **shim** (`tools/ctc_ide_shim.py`, bundled in the extension, spawned
  automatically) injects the user's CTC identity onto Copilot's requests and
  forwards **only `*.<GHE_DOMAIN>`** traffic to the central proxy — everything else
  tunnels direct, so the proxy's load is unchanged and other extensions keep
  working.
- The central proxy then does the usual mock `/v2/token` + PAT swap +
  integration-id spoof + `/responses` metering (guides 01, 04).

It's a **mode**: when ON, that window's Copilot bills the pool; when OFF, it's normal
Copilot. Not two Copilots side by side.

Enabling is **gated on Copilot readiness**: if the Copilot Chat extension isn't
installed, or VS Code detects no GitHub/GHE sign-in
(`vscode.authentication.getSession`), the toggle warns first. The check is
best-effort — each warning offers "Enable anyway" so a scope/provider mismatch can't
lock out a user who really is signed in.

## Configuration (zero-touch)

The extension reads the token, proxy host/port, and GHE domain from
`~/.config/ctc/env` — the file `ctc login` writes — so a user who ran the installer
configures **nothing** inside VS Code. VS Code settings (`ctc.proxyHost`,
`ctc.proxyPort`, `ctc.listenPort`, `ctc.gheDomain`) and `CTC: Set proxy token`
override the env file when set.

## Install (end user)

One command (the dashboard "Set up VS Code" card shows it with a fresh token):

```
curl -fsSLk https://<ctc-host>/install-vscode.sh | sh -s -- --token <TOKEN>
```

It installs the `ctc` launcher, runs `ctc login` (trusts the CA cert in the System
keychain + writes `~/.config/ctc/env`), and installs the extension `.vsix`. Then in
VS Code: reload, sign into Copilot, click `◆ CTC`.

Requires macOS and `python3` on PATH (for the shim), and the `code` CLI for the
install step.

## Deploying (operator)

`web/Dockerfile` builds the extension into `ctc-copilot.vsix` (the `extbuild`
stage) and serves it plus `install-vscode.sh` from `/srv/www`, with the deployment
host/scheme baked in — same mechanism as `install.sh`/`ctc`. Rebuild + redeploy the
web image to publish a new extension version.

Run the central proxy with `CTC_RESTRICT_CONNECT` **off** for IDE users (smart
routing means non-Copilot traffic never reaches the proxy anyway).

## Build from source (maintainer)

```
cd ide/ctc-vscode
npm install
npx @vscode/vsce package --allow-missing-repository --skip-license   # -> ctc-copilot-<v>.vsix
code --install-extension ctc-copilot-*.vsix
```

`npm run copy-shim` (run automatically on package) copies the single-source shim
from `tools/ctc_ide_shim.py` into `media/`.

## Out of scope (future)

- **Accountless activation** — users with no GHE account still can't pass Copilot's
  mandatory OAuth sign-in; that's a separate milestone.
- **Prompt caching** — the extension sends no `x-client-session-id`, so the session
  pin doesn't fire; fine for concrete-model chat, a risk for auto-mode
  (see `docs/reference` / metering notes).
