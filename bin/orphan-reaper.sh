#!/usr/bin/env bash
set -uo pipefail
shopt -s globstar nullglob
api="http://localhost:8989/api/v3"
key="CHANGE_ME_API_KEY"
min_tracked=500
min_age_days=2
keep_days=14
qroot="/mnt/4tbhdd/.orphan_quarantine"
dry=0
[[ ${1:-} == --dry-run ]] && dry=1
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
epkey() { [[ $(basename "$1") =~ S([0-9]+)E([0-9]+) ]] || return 1; printf '%s|%d|%d' "$(dirname "$(dirname "$1")")" "$((10#${BASH_REMATCH[1]}))" "$((10#${BASH_REMATCH[2]}))"; }
series=$(curl -sf "$api/series?apikey=$key") || { log "ABORT: sonarr unreachable"; exit 1; }
declare -A tracked=() covered=()
while IFS= read -r p; do
  [[ $p == __FAIL__ ]] && { log "ABORT: episodefile request failed"; exit 1; }
  p=$(sed 's#^/4tbhdd/#/mnt/4tbhdd/#; s#^/1tbhdd/#/mnt/1tbhdd/#; s#^/ssd/#/mnt/ssd/#; s#^/nvme/#/mnt/nvme/#' <<<"$p")
  tracked["$p"]=1
  if [[ -f $p ]] && k=$(epkey "$p"); then covered["$k"]=1; fi
done < <(for id in $(jq -r '.[].id' <<<"$series"); do curl -sf "$api/episodefile?seriesId=$id&apikey=$key" | jq -r '.[].path' || echo "__FAIL__"; done)
count=${#tracked[@]}
(( count < min_tracked )) && { log "ABORT: only $count tracked files, expected >= $min_tracked"; exit 1; }
n=0
now=$(date +%s)
for f in /mnt/4tbhdd/anime/**/*.{mkv,mp4} /mnt/4tbhdd/tv/**/*.{mkv,mp4}; do
  [[ -n ${tracked["$f"]:-} ]] && continue
  k=$(epkey "$f") || { log "SKIP no SxxEyy: $f"; continue; }
  [[ -z ${covered["$k"]:-} ]] && { log "SKIP sonarr file for this episode missing, likely pending rescan: $f"; continue; }
  age=$(( (now - $(stat -c %Y "$f")) / 86400 ))
  (( age < min_age_days )) && { log "SKIP too new (${age}d): $f"; continue; }
  dest="$qroot/$(date +%F)/${f#/mnt/4tbhdd/}"
  if (( dry )); then
    log "WOULD MOVE: $f"
  else
    mkdir -p "$(dirname "$dest")" && mv -n "$f" "$dest" && log "MOVED: $f"
  fi
  n=$((n+1))
done
log "orphans: $n, tracked: $count, dry-run: $dry"
if (( ! dry )) && [[ -d $qroot ]]; then
  cutoff=$(date -d "-$keep_days days" +%F)
  for d in "$qroot"/*/; do
    [[ $(basename "$d") < $cutoff ]] && rm -rf -- "$d" && log "PURGED: $d"
  done
fi
