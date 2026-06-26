#!/bin/sh
# CTC launcher installer. Usage: curl -fsSLk https://<ctc-host>/install.sh | sh
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
  echo "ctc: macOS only for now. See TDD.md §6.3 for manual setup on other systems." >&2
  exit 1
fi

CTC_HOST="${CTC_HOST:-ctc.local}"
CTC_SCHEME="${CTC_SCHEME:-https}"   # rewritten to the deployment's web transport at build time
CTC_SRC="${CTC_SRC:-$CTC_SCHEME://$CTC_HOST/ctc}"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

echo "Installing ctc to $BIN_DIR/ctc ..."
case "$CTC_SRC" in
  http*://*) curl -fsSLk "$CTC_SRC" -o "$BIN_DIR/ctc";;
  *)         cp "$CTC_SRC" "$BIN_DIR/ctc";;          # local path (tests / dev)
esac
chmod +x "$BIN_DIR/ctc"

# Ensure ~/.local/bin is on PATH
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    case "${SHELL:-}" in *zsh) rc="$HOME/.zshrc";; *bash) rc="$HOME/.bashrc";; *) rc="$HOME/.profile";; esac
    printf '\n# Added by CTC installer\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc"
    echo "Added $BIN_DIR to PATH in $rc — restart your shell or run: export PATH=\"\$HOME/.local/bin:\$PATH\""
    ;;
esac

echo "✓ Installed."
if [ -n "$TOKEN" ]; then
  "$BIN_DIR/ctc" login --token "$TOKEN"
else
  echo "Next: ctc login"
fi
