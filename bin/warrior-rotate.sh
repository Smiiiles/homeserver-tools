#!/usr/bin/env bash
set -euo pipefail

ROTATION=(telegram githubtest2 rferl microsoftupdate radiofreeasia usgovernment voiceofamerica nihvideocast wikimediaetherpad nihnlmdigitalcollections weebly nihfitbir urlteam2)
IMAGE=atdr.meo.ws/archiveteam/warrior-dockerfile
STATE_DIR=/var/lib/warrior-rotate
STATE_FILE=$STATE_DIR/index

mkdir -p "$STATE_DIR"
idx=$(cat "$STATE_FILE" 2>/dev/null || echo -1)

available=$(curl -sf --compressed https://warriorhq.archiveteam.org/projects.json | jq -r '.projects[] | select(.title | startswith("[") | not) | .name') || { echo "Could not fetch project list, keeping current project"; exit 0; }
[ -z "$available" ] && { echo "Empty project list, keeping current project"; exit 0; }

n=${#ROTATION[@]}
for i in $(seq 1 "$n"); do
  next=$(( (idx + i) % n ))
  project=${ROTATION[$next]}
  if grep -qx "$project" <<< "$available"; then
    docker pull -q "$IMAGE" > /dev/null || true
    docker rm -f archiveteam-warrior > /dev/null 2>&1 || true
    docker run -d --name archiveteam-warrior --restart unless-stopped -p 8001:8001 --log-opt max-size=10m --log-opt max-file=3 -e DOWNLOADER=Smiles -e SELECTED_PROJECT="$project" -e CONCURRENT_ITEMS=4 "$IMAGE" > /dev/null
    echo "$next" > "$STATE_FILE"
    echo "Switched to $project"
    exit 0
  fi
done

echo "No project from rotation list is available, keeping current project"
