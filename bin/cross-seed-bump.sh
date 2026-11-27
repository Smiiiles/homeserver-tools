#!/bin/bash
set -uo pipefail
C=/home/htpc/docker/docker-compose.yml
D=/home/htpc/docker/cross-seed
B=/home/youruser/cross-seed-backups
L=/var/log/cross-seed-bump.log
log() { echo "$(date '+%F %T') $*" >> "$L"; }
NEW=$(curl -fsS "https://api.github.com/repos/cross-seed/cross-seed/releases?per_page=30" | jq -r '[.[] | select(.draft | not) | select(.tag_name | test("^v([7-9]|[1-9][0-9])\\."))] | sort_by(.published_at) | last | .tag_name // empty | ltrimstr("v")')
CUR=$(grep -oP 'ghcr\.io/cross-seed/cross-seed:\K\S+' "$C" | head -n 1)
[ -z "$NEW" ] && { log "no release found"; exit 1; }
[ "$NEW" = "$CUR" ] && exit 0
docker pull -q "ghcr.io/cross-seed/cross-seed:$NEW" > /dev/null 2>&1 || { log "image $NEW not on ghcr yet"; exit 0; }
mkdir -p "$B"
SNAP="$B/cross-seed-$CUR-$(date +%F-%H%M).db"
python3 -c "import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" "$D/cross-seed.db" "$SNAP" || { log "backup failed, staying on $CUR"; exit 1; }
sed -i "s|cross-seed/cross-seed:$CUR|cross-seed/cross-seed:$NEW|" "$C"
docker compose -f "$C" up -d cross-seed > /dev/null 2>&1
sleep 60
if [ "$(docker inspect -f '{{.State.Running}} {{.RestartCount}}' cross-seed)" = "true 0" ]; then
  log "updated $CUR -> $NEW"
else
  log "$NEW failed to start, rolled back to $CUR"
  docker stop cross-seed > /dev/null
  cp "$SNAP" "$D/cross-seed.db" && rm -f "$D/cross-seed.db-wal" "$D/cross-seed.db-shm"
  chown 1001:1001 "$D/cross-seed.db"
  sed -i "s|cross-seed/cross-seed:$NEW|cross-seed/cross-seed:$CUR|" "$C"
  docker compose -f "$C" up -d cross-seed > /dev/null 2>&1
fi
ls -1t "$B"/cross-seed-*.db 2> /dev/null | tail -n +8 | xargs -r rm -f
