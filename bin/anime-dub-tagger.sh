#!/usr/bin/env bash
set -uo pipefail
api="http://localhost:8989/api/v3"
key="CHANGE_ME_API_KEY"
label="anime-dub"
days=21
dry=0
[[ ${1:-} == --dry-run ]] && dry=1
log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
get() { curl -sf "$api/$1" -H "X-Api-Key: $key"; }
send() { curl -sf -X "$1" "$api/$2" -H "X-Api-Key: $key" -H 'Content-Type: application/json' -d "$3"; }
tags=$(get tag) || { log "ABORT: sonarr unreachable"; exit 1; }
tid=$(jq -r --arg l "$label" '.[] | select(.label == $l) | .id' <<<"$tags")
if [[ -z $tid ]]; then
  if (( dry )); then
    tid=0
    log "would create tag $label"
  else
    tid=$(send POST tag "{\"label\":\"$label\"}" | jq -r .id) || { log "ABORT: tag create failed"; exit 1; }
    log "created tag $label id=$tid"
  fi
fi
series=$(get series) || { log "ABORT: series fetch failed"; exit 1; }
anime_ids=$(jq -r '.[] | select(.path | startswith("/4tbhdd/anime/")) | .id' <<<"$series")
cutoff=$(date -u -d "-$days days" +%FT%T)
history=$(get "history?pageSize=2000&eventType=1&sortKey=date&sortDirection=descending") || { log "ABORT: history fetch failed"; exit 1; }
declare -A dub=()
for id in $(jq -r --arg c "$cutoff" '[.records[] | select(.date >= $c) | select(any(.customFormats[]?; .name | test("Dual Audio|Multi Audio"))) | .seriesId] | unique | .[]' <<<"$history"); do
  dub[$id]=1
done
for id in $anime_ids; do
  [[ -n ${dub[$id]:-} ]] && continue
  if get "episodefile?seriesId=$id" | jq -e '(map(.seasonNumber) | max) as $s | any(.[] | select(.seasonNumber == $s); (.mediaInfo.audioLanguages // "") | test("eng"; "i"))' > /dev/null 2>&1; then
    dub[$id]=1
  fi
done
add=()
remove=()
n=0
for id in $anime_ids; do
  read -r has name < <(jq -r --argjson i "$id" --argjson t "$tid" '.[] | select(.id == $i) | "\((.tags | index($t)) != null) \(.title)"' <<<"$series")
  [[ -n ${dub[$id]:-} ]] && n=$((n+1))
  if [[ -n ${dub[$id]:-} && $has == false ]]; then add+=("$id"); log "ADD: $name"; fi
  if [[ -z ${dub[$id]:-} && $has == true ]]; then remove+=("$id"); log "REMOVE: $name"; fi
done
apply() {
  local mode=$1
  shift
  (( $# )) || return 0
  local ids
  ids=$(printf '%s\n' "$@" | jq -s -c .)
  send PUT series/editor "{\"seriesIds\":$ids,\"tags\":[$tid],\"applyTags\":\"$mode\"}" > /dev/null && log "applied $mode to $# series" || log "FAILED $mode"
}
if (( ! dry )); then
  apply add "${add[@]}"
  apply remove "${remove[@]}"
fi
log "dubbed anime series: $n, added: ${#add[@]}, removed: ${#remove[@]}, dry-run: $dry"
