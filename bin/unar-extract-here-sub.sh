#!/bin/bash
for f in "$@"; do
  unar -f -o "$(dirname "$f")" "$f"
done
