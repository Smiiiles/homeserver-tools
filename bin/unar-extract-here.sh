#!/bin/bash
for f in "$@"; do
  unar -D -f -o "$(dirname "$f")" "$f"
done
