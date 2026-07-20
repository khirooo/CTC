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

Enabling is **gated on Copilot being installed** (a reliable check). It deliberately
does **not** try to detect "signed in" — there's no dependable public API for a GHE
Copilot session, and an earlier `vscode.authentication.getSession` gate produced
false negatives that warned users who were in fact signed in. If Copilot Chat isn't
installed the toggle warns first, with an "Enable anyway" escape.

## Critical: sign into Copilot *while CTC is on*

**The Copilot sign-in must happen with CTC already ON, or chat silently bypasses the
proxy and bills the user's own seat.** Turning CTC on for an *already-signed-in*
Copilot is **not** enough — a window reload isn't either.

Why (root cause, proven 2026-07-20 by socket inspection): the Copilot Chat client
runs in the VS Code extension host (a Node process) and talks to
`copilot-api.<GHE>` over a **persistent, keep-alive/pooled TLS connection** — one
socket, opened once and reused across messages (confirmed with
`lsof -nP -iTCP@<copilot-api-IP>` showing an ESTABLISHED direct socket held while
idle, with **zero** traffic on the central proxy). Node binds a pooled connection's
proxy route **when it creates the socket** (≈ at sign-in) and then keeps it open, so:

- **Sign in with CTC on** → the pooled socket is created *to the shim*
  (`127.0.0.1:8899`) → all chat routes through CTC. ✅
- **Sign in with CTC off** → the pooled socket is created **direct** to the GHE IP and
  held open → flipping `http.proxy` afterward never rebuilds it → chat keeps going
  direct. ❌

Short-lived control-plane calls (`/copilot_internal/user`, `/v2/token`) *are*
re-created per request, so they pick up the toggle after a reload — but the pooled
chat socket does not. **Operator/onboarding rule: turn CTC on first, then sign out +
sign back into Copilot.** (Sign-in itself must be done with CTC on but *not* mid-MITM
of the OAuth redirect — the shim only forwards `copilot-api`/GHE hosts, so OAuth to
github.com is unaffected.)

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

## Next step (planned): smart bypass detection → prompt re-sign-in

The "sign in while CTC on" rule above is load-bearing and easy to get wrong, so the
extension should **detect an actual bypass and prompt only then** — never nag a
correctly-routing user. Design (validated by manual `lsof`, not yet built):

- **The signal.** The extension runs *inside* the same extension-host process that
  owns the bypassing socket, so `process.pid` **is** that process. Resolve
  `copilot-api.<gheDomain>` (`dns.resolve4`, handle multiple IPs), then check the
  extension's *own* sockets:

  ```
  lsof -nP -iTCP@<copilot-api-IP> -a -p <process.pid>   # count ESTABLISHED
  ```

  **count > 0 ⇒ a direct socket to copilot-api exists ⇒ chat is bypassing CTC.** This
  has no false positives: when routing correctly the ext host connects to
  `127.0.0.1:8899` (the shim), never to the GHE IP directly.

- **Why poll, not one-shot.** The keep-alive pool **idle-closes** (observed live:
  2 sockets → 0 after a short idle). A single check at enable time gives false
  negatives. Instead **poll while CTC is on** (every few seconds); the socket
  reappears whenever Copilot chats, so an active bypass is caught within one interval.

- **The prompt.** The first time a direct socket is observed, show a warning —
  *"Copilot is connecting directly and bypassing CTC — sign out and back in to route
  it through the pool"* — with a **Sign out** action. Correctly-routing users never
  see it; bypassing users are prompted exactly once.

- **Caveats.** macOS-only (`lsof` on the own PID, no sudo needed — matches the shim's
  current macOS-only constraint). Alternative robust fix that removes the sign-in-order
  rule entirely = transparent MITM (`/etc/hosts` maps `copilot-api.<GHE>` → the proxy,
  proxy listens on :443 and routes by TLS SNI, intercepting below `http.proxy`); bigger
  change, tracked separately.

## Out of scope (future)

- **Accountless activation** — users with no GHE account still can't pass Copilot's
  mandatory OAuth sign-in; that's a separate milestone.
- **Prompt caching** — the extension sends no `x-client-session-id`, so the session
  pin doesn't fire; fine for concrete-model chat, a risk for auto-mode
  (see `docs/reference` / metering notes).
