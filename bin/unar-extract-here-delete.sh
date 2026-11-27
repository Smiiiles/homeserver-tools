#!/bin/bash
for f in "$@"; do
  D=$(dirname "$f")
  unar -D -f -o "$D" "$f" && rm "$f"
done
