#!/usr/bin/env bash
#
# uninstall.sh — remove the `wcup` launcher installed by install.sh.
# The repo itself is left untouched (just delete the folder to remove it).
#
set -euo pipefail

BIN_DIR="${PREFIX:-$HOME/.local/bin}"

if [ -f "$BIN_DIR/wcup" ]; then
  rm -f "$BIN_DIR/wcup"
  printf '\033[32m✓\033[0m removed %s\n' "$BIN_DIR/wcup"
else
  printf '• no launcher found at %s (nothing to do)\n' "$BIN_DIR/wcup"
fi
