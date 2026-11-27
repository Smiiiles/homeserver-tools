#!/bin/bash
LIBRARY_PATHS=(
  "/mnt/1tbhdd/anime"
  "/mnt/1tbhdd/movies"
  "/mnt/1tbhdd/tv"
  "/mnt/1tbhdd/music"
  "/mnt/4tbhdd/anime"
  "/mnt/4tbhdd/movies"
  "/mnt/4tbhdd/tv"
  "/mnt/ssd/anime"
  "/mnt/ssd/movies"
  "/mnt/ssd/tv"
  "/mnt/ssd/tdarr-cache"
  "/mnt/nvme/anime"
  "/mnt/nvme/movies"
  "/mnt/nvme/tv"
  "/mnt/nvme/tdarr-cache"
  "/mnt/nvme/music"
)

for path in "${LIBRARY_PATHS[@]}"; do
  if [ -d "$path" ]; then
    chown -R 1001:1001 "$path"
    chmod -R ug+rwX "$path"
  fi
done
