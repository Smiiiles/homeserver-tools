#!/bin/bash
BACKUP_DIR="/mnt/1tbhdd/backups/docker"
DATE=$(date +%Y%m%d)
mkdir -p $BACKUP_DIR

HOMARR_VOLUME=$(docker inspect homarr --format '{{range .Mounts}}{{if eq .Destination "/appdata"}}{{.Source}}{{end}}{{end}}')

tar -czf $BACKUP_DIR/docker-config-$DATE.tar.gz \
  --exclude=navidrome/cache \
  /home/htpc/docker/docker-compose.yml \
  /home/htpc/docker/immich.env \
  /home/htpc/docker/jellyfin/config/data/jellyfin.db \
  /home/htpc/docker/jellyfin/config/plugins \
  /home/htpc/docker/jellyfin/config/root \
  /home/htpc/docker/jellyseerr/config \
  /home/htpc/docker/jfa-go/config \
  /home/htpc/docker/radarr/config \
  /home/htpc/docker/sonarr/config \
  /home/htpc/docker/lidarr/config \
  /home/htpc/docker/prowlarr/config \
  /home/htpc/docker/bazarr/config \
  /home/htpc/docker/qbittorrent/config \
  /home/htpc/docker/gluetun \
  /home/htpc/docker/caddy \
  /home/htpc/docker/pihole \
  /home/htpc/docker/homarr \
  /home/htpc/docker/uptime-kuma/kuma.db \
  /home/htpc/docker/list-sync \
  /home/htpc/docker/autobrr/config \
  /home/htpc/docker/recyclarr/config \
  /home/htpc/docker/kometa/config \
  /home/htpc/docker/tdarr/server/Tdarr/Plugins/Local \
  /home/htpc/docker/tdarr/configs \
  /home/htpc/docker/.env \
  /home/htpc/docker/cleanuparr \
  /home/htpc/docker/unbound \
  /home/htpc/docker/cross-seed \
  /home/htpc/docker/slskd \
  /home/htpc/docker/aurral/config \
  /home/htpc/docker/tdarr/server/hardlink_skipped.txt \
  /home/htpc/docker/searxng \
  /home/htpc/docker/paperless/docker-compose.yml \
  /home/htpc/docker/paperless/docker-compose.env \
  /home/htpc/docker/paperless/.env \
  /home/htpc/docker/navidrome \
  /home/youruser/portainer \
  /home/youruser/calagopus-panel/docker-compose.yml \
  /home/youruser/calagopus-panel/compose.yml \
  /home/youruser/calagopus-panel/.env \
  /home/youruser/calagopus-panel/wings-config.yml \
  /home/youruser/calagopus-panel/data \
  /etc/calagopus-wings \
  $HOMARR_VOLUME \
  2>/dev/null

find $BACKUP_DIR -name "*.tar.gz" -mtime +15 -delete

IMMICH_BACKUP_DIR="/mnt/1tbhdd/photos/backups"
mkdir -p $IMMICH_BACKUP_DIR
docker exec -t immich_postgres pg_dumpall --username=immich | gzip > $IMMICH_BACKUP_DIR/immich-db-backup-$(date +%Y%m%dT%H%M%S)-manual.sql.gz

DB_BACKUP_DIR="/mnt/1tbhdd/backups/db"
mkdir -p $DB_BACKUP_DIR
docker exec calagopus-panel-db-1 sh -c 'exec pg_dumpall -U "$POSTGRES_USER"' | gzip > $DB_BACKUP_DIR/calagopus-db-$DATE.sql.gz
ls -1t $DB_BACKUP_DIR/calagopus-db-*.sql.gz | tail -n +16 | xargs -r rm --

SYSBACKUP_DIR="/mnt/1tbhdd/backups/system"
mkdir -p $SYSBACKUP_DIR
tar -czf $SYSBACKUP_DIR/system-config-$DATE.tar.gz \
  /etc/fstab \
  /etc/hostname \
  /etc/hosts \
  /etc/crontab \
  /var/spool/cron/ \
  /usr/local/bin \
  2>/dev/null

find $SYSBACKUP_DIR -name "*.tar.gz" -mtime +15 -delete
find $IMMICH_BACKUP_DIR -name "immich-db-backup-*manual*" -mtime +15 -delete
