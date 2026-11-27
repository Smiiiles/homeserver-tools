#!/bin/bash
BACKUP_DIR="/mnt/1tbhdd/backups/misc"
DATE=$(date +%Y%m%d)
mkdir -p $BACKUP_DIR

tar -czf $BACKUP_DIR/terraria-$DATE.tar.gz \
  /home/youruser/.local/share/Terraria/tModLoader \
  /etc/systemd/system/terraria.service \
  2>/dev/null

tar -czf $BACKUP_DIR/custom-scripts-$DATE.tar.gz \
  /usr/local/bin/backup-docker.sh \
  /usr/local/bin/backup-misc.sh \
  /home/youruser/update_all_mods.sh \
  /home/youruser/check_stale_mods.sh \
  /home/youruser/rename_subs.sh \
  /home/youruser/immich_dedup.py \
  2>/dev/null

find $BACKUP_DIR -name "*.tar.gz" -mtime +15 -delete
