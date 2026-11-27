#!/bin/bash
for f in /etc/duckdns/*.env; do
  unset DUCK_DOMAIN DUCK_TOKEN
  . "$f"
  r=$(curl -fsS "https://www.duckdns.org/update?domains=${DUCK_DOMAIN}&token=${DUCK_TOKEN}&ip=")
  echo "$(date '+%F %T') $(basename "$f" .env) $r"
done > /var/log/duckdns-update.log
