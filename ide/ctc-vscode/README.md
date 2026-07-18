# CTC Copilot (VS Code extension)

A one-click toggle that routes the **GitHub Copilot Chat extension** through the CTC
credit proxy, so chat bills the shared pool instead of your own seat — without a fresh
profile and without hand-editing settings.

It's a **mode**: when CTC is ON, this window's Copilot bills the pool; when OFF, it's
normal Copilot. (It is not two Copilots side by side.)

## How it works

Clicking `◆ CTC` in the status bar:
1. saves your current `http.proxy`, then points it at a **local identity shim**
   (`http://127.0.0.1:<listenPort>`) and sets `http.proxyStrictSSL:false`,
   `http.proxySupport:on`;
2. clears the `github.copilot.advanced.authProvider: "github-enterprise"` setting if
   present (it conflicts with the CTC path);
3. starts the shim (a hidden `python3` process) and reloads the window.

The shim injects your CTC identity onto Copilot's requests and forwards **only**
`*.<gheDomain>` traffic to the central CTC proxy — everything else tunnels directly, so
the proxy only ever sees Copilot/GHE calls. Toggling off restores your settings.

## One-time setup

1. **Trust the proxy CA** (macOS; the extension's / VS Code's network stack uses the
   system trust store):
   ```
   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain cert.pem
   ```
   (Use the same `cert.pem` your CTC proxy serves.)
2. **Set your token**: Command Palette → `CTC: Set proxy token` (from the dashboard
   "Set up CLI" panel).
3. **Configure** (Settings → search "CTC"): `ctc.proxyHost`, `ctc.proxyPort` (8080),
   `ctc.gheDomain` (e.g. `sita.ghe.com`). `ctc.listenPort` defaults to 8899.

Requires `python3` on PATH (macOS ships it). The central proxy should run with
`CTC_RESTRICT_CONNECT` **off** for this window (smart routing means non-Copilot traffic
never reaches the proxy anyway).

## Daily use

- Sign into Copilot normally (with CTC OFF the first time).
- Click `◆ CTC` → window reloads → Copilot chat now bills the pool.
- Click again → back to normal Copilot.

## Build / package

```
npm install
npm run compile            # tsc -> out/  (copy-shim runs via vscode:prepublish)
npx @vscode/vsce package   # -> ctc-copilot-<version>.vsix
code --install-extension ctc-copilot-*.vsix
```

`npm run copy-shim` copies the single-source shim from `../../tools/ctc_ide_shim.py`
into `media/` (bundled into the vsix). macOS-only for now, like the `ctc` CLI.
