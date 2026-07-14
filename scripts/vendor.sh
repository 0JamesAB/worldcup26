#!/bin/sh
# vendor.sh — refresh the in-tree puretui/ from the library repo.
#
# The app keeps a vendored copy of puretui so `git clone && ./install.sh`
# stays zero-pip. Pin to a tag (preferred) or SHA:
#
#   ./scripts/vendor.sh v0.6.0
#
set -e
REF="${1:?usage: vendor.sh <tag-or-sha>}"
REPO="https://github.com/0JamesAB/puretui"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone --quiet --depth 1 --branch "$REF" "$REPO" "$TMP/puretui" 2>/dev/null \
  || (git clone --quiet "$REPO" "$TMP/puretui" && git -C "$TMP/puretui" checkout --quiet "$REF")
rm -rf puretui
cp -R "$TMP/puretui/puretui" puretui
echo "$REF" > puretui/.vendored-ref
echo "vendored puretui @ $REF"
