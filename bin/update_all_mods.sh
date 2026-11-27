#!/bin/bash

TERRARIA_SERVICE="terraria.service"
MODS_DIR="/home/youruser/.local/share/Terraria/tModLoader/Mods"
WORLD_DIR="/home/youruser/.local/share/Terraria/tModLoader/Worlds"
WORLD_BACKUP_DIR="/mnt/1tbhdd/backups/terraria_worlds"
STEAMCMD_DIR="/home/youruser/steamcmd"
APP_ID=1281930

mkdir -p "$WORLD_BACKUP_DIR"

echo "$(date): Backing up worlds..."
tar -czf "$WORLD_BACKUP_DIR/worlds-$(date +%Y%m%d_%H%M%S).tar.gz" -C "$WORLD_DIR" .
find "$WORLD_BACKUP_DIR" -name "*.tar.gz" -mtime +14 -delete

echo "$(date): Stopping terraria server..."
sudo systemctl stop "$TERRARIA_SERVICE"

echo "$(date): Reading deployed mod workshop IDs..."
WORKSHOP_IDS=()
PINNED_IDS=("2563587529" "2824688072")  # FasterBuilding dead mod, CalamityMod now local-only
for link in "$MODS_DIR"/*; do
    if [ -L "$link" ]; then
        target=$(readlink -f "$link")
        id=$(echo "$target" | grep -oP '/workshop/content/'"$APP_ID"'/\K[0-9]+')
        if [ -n "$id" ] && [[ ! " ${PINNED_IDS[*]} " =~ " ${id} " ]]; then
            WORKSHOP_IDS+=("$id")
        fi
    fi
done

WORKSHOP_IDS=($(printf "%s\n" "${WORKSHOP_IDS[@]}" | sort -u))

if [ ${#WORKSHOP_IDS[@]} -eq 0 ]; then
    echo "$(date): No workshop mods found via symlinks, aborting update."
    sudo systemctl start "$TERRARIA_SERVICE"
    exit 1
fi

echo "$(date): Found ${#WORKSHOP_IDS[@]} mods to update: ${WORKSHOP_IDS[*]}"

STEAMCMD_ARGS="+login anonymous"
for id in "${WORKSHOP_IDS[@]}"; do
    STEAMCMD_ARGS="$STEAMCMD_ARGS +workshop_download_item $APP_ID $id"
done
STEAMCMD_ARGS="$STEAMCMD_ARGS +quit"

echo "$(date): Running steamcmd update..."
"$STEAMCMD_DIR/steamcmd.sh" $STEAMCMD_ARGS
echo "$(date): Relinking mods to latest versions..."
for id in "${WORKSHOP_IDS[@]}"; do
    ITEM_DIR="/home/youruser/.local/share/Steam/steamapps/workshop/content/$APP_ID/$id"
    LATEST_VER=$(ls -1 "$ITEM_DIR" | grep -v workshop.json | sort -V | tail -n1)
    TMOD_FILE=$(find "$ITEM_DIR/$LATEST_VER" -name "*.tmod" | head -n1)
    if [ -n "$TMOD_FILE" ]; then
        LINK_NAME=$(basename "$TMOD_FILE")
        ln -sf "$TMOD_FILE" "$MODS_DIR/$LINK_NAME"
        echo "$(date): Relinked $LINK_NAME -> $LATEST_VER"
    else
        echo "$(date): WARNING - no .tmod found for workshop id $id in $LATEST_VER"
    fi
done

echo "$(date): Restarting terraria server..."
sudo systemctl start "$TERRARIA_SERVICE"

echo "$(date): Done."
