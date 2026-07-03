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

# Ensure the GitHub Copilot CLI (the 'copilot' binary the launcher execs) is present.
if command -v copilot >/dev/null 2>&1; then
  echo "✓ GitHub Copilot CLI already installed ($(command -v copilot))."
else
  echo "GitHub Copilot CLI not found — installing (npm install -g @github/copilot) ..."
  copilot_installed=0
  if command -v npm >/dev/null 2>&1; then
    if npm install -g @github/copilot; then
      copilot_installed=1
    else
      echo "npm install -g @github/copilot failed." >&2
    fi
  elif command -v brew >/dev/null 2>&1; then
    echo "npm not found — trying brew install --cask copilot-cli ..."
    if brew install --cask copilot-cli; then
      copilot_installed=1
    else
      echo "brew install --cask copilot-cli failed." >&2
    fi
  fi

  if [ "$copilot_installed" -eq 1 ] && command -v copilot >/dev/null 2>&1; then
    echo "✓ GitHub Copilot CLI installed ($(command -v copilot))."
  else
    echo "Could not install the GitHub Copilot CLI automatically." >&2
    echo "Install Node (https://nodejs.org) then run: npm install -g @github/copilot" >&2
    echo "(or: brew install --cask copilot-cli)" >&2
    echo "ctc will not work until 'copilot' is on your PATH." >&2
  fi
fi

if [ -n "$TOKEN" ]; then
  "$BIN_DIR/ctc" login --token "$TOKEN"
else
  echo "Next: ctc login"
fi
