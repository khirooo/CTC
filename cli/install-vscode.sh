#!/bin/sh
# CTC VS Code installer — one command sets up the Copilot extension to route
# through CTC. Usage: curl -fsSLk https://<ctc-host>/install-vscode.sh | sh -s -- --token <TOKEN>
#
# It: installs the `ctc` launcher, runs `ctc login` (trusts the CA cert + writes
# ~/.config/ctc/env with the token, proxy host/port, and GHE domain), then
# installs the CTC Copilot VS Code extension. The extension reads that env file,
# so there is nothing to configure inside VS Code — just click the ◆ CTC button.
set -eu

TOKEN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --token) if [ $# -ge 2 ]; then TOKEN="$2"; shift 2; else TOKEN=""; shift; fi;;
    --token=*) TOKEN="${1#--token=}"; shift;;
    --) shift;;
    *) shift;;
  esac
done

if [ "$(uname)" != "Darwin" ]; then
  echo "ctc: macOS only for now." >&2
  exit 1
fi

CTC_HOST="${CTC_HOST:-ctc.local}"
CTC_SCHEME="${CTC_SCHEME:-https}"   # rewritten to the deployment's web transport at build time
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

# 1) Install the ctc launcher (needed for `ctc login`: cert trust + env file).
echo "Installing ctc launcher ..."
CTC_SRC="$CTC_SCHEME://$CTC_HOST/ctc"
case "$CTC_SRC" in
  http*://*) curl -fsSLk "$CTC_SRC" -o "$BIN_DIR/ctc";;
  *)         cp "$CTC_SRC" "$BIN_DIR/ctc";;
esac
chmod +x "$BIN_DIR/ctc"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    case "${SHELL:-}" in *zsh) rc="$HOME/.zshrc";; *bash) rc="$HOME/.bashrc";; *) rc="$HOME/.profile";; esac
    printf '\n# Added by CTC installer\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc"
    ;;
esac

# 2) `ctc login`: trusts the CA cert and writes ~/.config/ctc/env (token, proxy,
#    GH_HOST). The extension + shim both read this — no manual VS Code setup.
if [ -n "$TOKEN" ]; then
  "$BIN_DIR/ctc" login --token "$TOKEN"
else
  "$BIN_DIR/ctc" login
fi

# 3) Install the VS Code extension.
if ! command -v code >/dev/null 2>&1; then
  echo "VS Code 'code' command not found on PATH." >&2
  echo "In VS Code: Command Palette -> 'Shell Command: Install code command in PATH', then re-run." >&2
  exit 1
fi
VSIX="$(mktemp -t ctc-copilot).vsix"
echo "Downloading the CTC Copilot extension ..."
curl -fsSLk "$CTC_SCHEME://$CTC_HOST/ctc-copilot.vsix" -o "$VSIX"
code --install-extension "$VSIX" --force
rm -f "$VSIX"

echo ""
echo "✓ Done. In VS Code: reload the window, sign into Copilot, then click the"
echo "  ◆ CTC button (bottom-right) to route Copilot through CTC. No settings to edit."
