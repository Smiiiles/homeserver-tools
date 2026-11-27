#!/bin/bash
DEST=$(kdialog --getexistingdirectory ~ --title "Extract to")
[ -n "$DEST" ] || exit 0
for f in "$@"; do
  unar -f -o "$DEST" "$f"
done
