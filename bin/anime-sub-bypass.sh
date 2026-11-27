#!/usr/bin/env bash
set -uo pipefail
api="http://localhost:8989/api/v3"
key="CHANGE_ME_API_KEY"
label="anime-dub"
min=1650
state="/var/lib/anime-sub-bypass/failed"
dry=0
[[ ${1:-} == --dry-run ]] && dry=1
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
get() { curl -sf "$api/$1" -H "X-Api-Key: $key"; }
send() { curl -sf -X "$1" "$api/$2" -H "X-Api-Key: $key" -H 'Content-Type: application/json' -d "$3"; }
mkdir -p "${state%/*}" && touch "$state"
tail -n 500 "$state" > "$state.tmp" && mv "$state.tmp" "$state"
tid=$(get tag | jq -r --arg l "$label" '.[] | select(.label == $l) | .id') || { log "ABORT: sonarr unreachable"; exit 1; }
[[ -z $tid ]] && exit 0
get "queue?pageSize=500&includeSeries=true&includeEpisode=true" | jq -r --argjson t "$tid" --argjson m "$min" '.records[] | select((.status | ascii_downcase) == "delay" and ((.series.tags // []) | index($t)) != null and .customFormatScore > $m and (any(.customFormats[]?; .name | test("Dual Audio|Multi Audio")) | not)) | "\(.id)\t\(.customFormatScore)\t\(.title)"' | while IFS=$'\t' read -r id score title; do
  grep -qx "$id" "$state" && continue
  if (( dry )); then
    log "WOULD GRAB: $score $title"
  elif send POST "queue/grab/$id" '{}' > /dev/null; then
    log "GRABBED: $score $title"
  else
    printf '%s\n' "$id" >> "$state"
    log "FAILED (not retrying): $id $title"
  fi
done
