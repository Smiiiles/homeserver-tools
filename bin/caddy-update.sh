#!/bin/bash
set -euo pipefail
compose=/home/htpc/docker/docker-compose.yml
dir=/home/htpc/docker/caddy
db=$dir/geoip/dbip-country-lite.mmdb
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
echo "== $(date -Is)"
for m in "$(date +%Y-%m)" "$(date -d "$(date +%Y-%m-01) -1 month" +%Y-%m)"; do
  if curl -fsSL --retry 3 "https://download.db-ip.com/free/dbip-country-lite-$m.mmdb.gz" -o "$tmp/db.gz"; then
    gunzip -c "$tmp/db.gz" > "$tmp/db.mmdb"
    break
  fi
done
if [ -s "$tmp/db.mmdb" ] && ! cmp -s "$tmp/db.mmdb" "$db"; then
  install -m 644 "$tmp/db.mmdb" "$db"
  echo "geoip db updated ($m)"
fi
[ -s "$db" ] || { echo "no geoip db, aborting"; exit 1; }
docker compose -f "$compose" build --pull caddy
docker run --rm --network none -v "$dir/config:/etc/caddy:ro" -v "$dir/geoip:/geoip:ro" -v "$tmp:/var/log/caddy" caddy-geo:latest caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose -f "$compose" up -d caddy
sleep 5
docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
echo "done"
