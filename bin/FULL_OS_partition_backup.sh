#!/bin/bash
set -e

# This backs up configs, app data, databases, and system settings, not the actual
# OS install, installed packages, docker images, or anything else you'd just
# redownload/reinstall from Fedora repos, Steam, or Docker Hub. If you're restoring
# after an OS swap, reinstall your packages/containers first, then drop this stuff
# back on top.

BACKUP_DIR="/mnt/1tbhdd/backups"
BACKUP="$BACKUP_DIR/FULL_OS_partition_backup_$(date +%Y%m%d)"
IMMICH_DUMP="$BACKUP_DIR/immich-db-backup-manual.sql.gz"

mkdir -p "$BACKUP_DIR"
rm -f "$BACKUP.tar" "$BACKUP.tar.gz"
rm -f "$IMMICH_DUMP"

docker exec -t immich_postgres pg_dumpall --username=immich | gzip > "$IMMICH_DUMP"

tar --one-file-system -cvf "$BACKUP.tar" \
  --exclude='*/.cache' \
  --exclude='*/cache' \
  --exclude='*/Thumbnails' \
  --exclude='/home/htpc/.kodi/userdata/thumbnails' \
  --exclude='*/__pycache__' \
  --exclude='*/.local/share/Trash' \
  --exclude='/home/youruser/Steam/steamapps/workshop' \
  --exclude='/home/youruser/Steam/steamapps/common' \
  --exclude='/home/youruser/.local/share/Terraria/tModLoaderServer' \
  --exclude='kodisyncqueue.db' \
  --exclude='/home/htpc/docker/jellyfin/config/metadata/library' \
  --exclude='/home/htpc/docker/jellyfin/config/metadata/People' \
  --exclude='/home/htpc/docker/jellyfin/config/metadata/Genre' \
  --exclude='/home/htpc/docker/jellyfin/config/metadata/Studio' \
  --exclude='/home/htpc/docker/jellyfin/config/metadata/views' \
  --exclude='/home/htpc/docker/tdarr/server/Tdarr/DB2/JobReports' \
  --exclude='/home/htpc/docker/tdarr/server/Tdarr/Backups' \
  --exclude='/home/htpc/docker/sonarr/config/MediaCover' \
  --exclude='/home/htpc/docker/radarr/config/MediaCover' \
  /home/htpc \
  /home/youruser \
  /etc/systemd/system \
  /etc/fstab \
  /etc/hosts \
  /etc/hostname \
  /etc/samba/smb.conf \
  /etc/sudoers \
  /etc/systemd/resolved.conf.d \
  /etc/yum.repos.d \
  /etc/crontab \
  /var/spool/cron \
  /etc/firewalld \
  /root/.ssh \
  /root/anaconda-ks.cfg \
  /usr/local/bin \
  /var/lib/docker/volumes/8df299a6f18f0b14572d3f66d3595588c3bf32826b7f5224c8e75fd42618bc5a/_data

tar --append -vf "$BACKUP.tar" \
  -C / home/youruser/.local/share/Terraria/tModLoaderServer/serverconfig.txt

tar --append -vf "$BACKUP.tar" \
  -C / "${IMMICH_DUMP#/}"

gzip -f "$BACKUP.tar"

rm -f "$IMMICH_DUMP"
find "$BACKUP_DIR" -maxdepth 1 -name "FULL_OS_partition_backup_*.tar.gz" -mtime +15 -delete

echo "Backup done: $BACKUP.tar.gz"
