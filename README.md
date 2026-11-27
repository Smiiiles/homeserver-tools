# homeserver-tools

Small scripts that keep a Fedora home server running: VPN health, backups, disk and GPU alerts, cleanup for qBittorrent and the *arr apps, and a few helpers around them. They go with [homeserver-stack](https://github.com/Smiiiles/homeserver-stack).

Written with Claude (Anthropic). Each script is standalone. Read one before you run it, because the paths and ports are set for one specific server.

## Scripts

| Area | Scripts |
| --- | --- |
| VPN | `gluetun-deps-guard.py` recreates containers that lost gluetun's network after a gluetun restart. `gluetun-failover.py` switches VPN servers when the exit stops working. `gluetun-flap-alert.py` mails when gluetun keeps restarting. `airvpn-status` lists AirVPN servers in a country by load |
| Monitoring | `disk-alert` pushes disk usage to an Uptime Kuma push monitor. `gpu-reset-watchdog.sh` reboots when an amdgpu reset loses VRAM. `cc-bench.py` runs speedtests against servers in several countries. `htpc-status`, `htpc-status-http` |
| Backups | `backup-docker.sh`, `backup-misc.sh`, `FULL_OS_partition_backup.sh` |
| Server | `duckdns-update.sh`, `caddy-update.sh` (refreshes the GeoIP database and rebuilds Caddy), `warrior-rotate.sh` (rotates ArchiveTeam Warrior projects), `update_all_mods.sh` (tModLoader Workshop mods via steamcmd) |
| Library | `orphan-reaper.sh` quarantines video files Sonarr and Radarr don't know about. `fix-media-permissions.sh`. `tdarr-hardlink-requeue.py` requeues files Tdarr skipped while they still had hardlinks. `host-ffmpeg-wrapper.sh`, `host-ffprobe-wrapper.sh`. `jf-watched-report.py` lists watched media by size. `codec-relabel.py` fixes codec tokens in file names. `redl-check.py`, `redl-delete.py` check that watched media can be fetched again before deleting it |
| *arr apps | `arr-fail-dangerous.py` sets "fail downloads" for executables on all indexers. `anime-dub-tagger.sh` tags dubbed anime in Sonarr. `anime-sub-bypass.sh` force-grabs releases that a delay profile holds back. `sonarr-cf-dedupe.py` creates custom formats that cancel out overlapping release-group tiers |
| qBittorrent | `qbit-missing-reaper.py` removes torrents stuck on missing files. `qbit-speed-schedule.py` switches speed limits by time of day. `qbit-tracker-stats.py`, `qbit-ratio-log.py` keep stats that survive removed torrents. `reseed`, `reseed-archive.py`, `reseed-watch.py` archive .torrent files and data fingerprints so a torrent can be verified and seeded again later |
| cross-seed | `cross-seed-bump.sh` moves the pinned image to the newest prerelease and rolls back if it fails to start. `cross-seed-cleanup.py` removes dead cross-seeds. `cross-seed-indexers.py` syncs Prowlarr's indexers into cross-seed |
| One Pace | `onepace-sync.py` adds new dubbed One Pace releases from the RSS feed to qBittorrent and links them into the library. `onepace-swap.py` swaps a full batch into the library. `muhn-sync.py` fills dub gaps from Muhn Pace via rclone |
| Dolphin | `unar-extract-here.sh`, `unar-extract-here-sub.sh`, `unar-extract-here-delete.sh`, `unar-extract-to.sh` |

## Config

Everything that was a secret or a local address has a placeholder now:

- API keys are `CHANGE_ME_API_KEY`. Put in your own Sonarr, Radarr or Prowlarr key.
- Service URLs point to `localhost`, since the scripts run on the server itself.
- Mail settings are read from `/etc/homeserver-tools/smtp.env` (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_TO`).
- qBittorrent login is read from `/etc/onepace-sync/qbit.env` (`QB_USER`, `QB_PASS`).
- `cross-seed-indexers.py`: `CROSS_SEED_EXCLUDE` is a comma-separated list of Prowlarr indexer names to skip.
- `muhn-sync.py`: `MUHN_FOLDER_ID` and `MUHN_WP_FOLDER_ID` are the Google Drive folder IDs.
- `onepace-swap.py`: `ONEPACE_HASH` is the infohash of the batch torrent.
- Paths like `/mnt/4tbhdd` and `/home/htpc/docker` match homeserver-stack. Change them to your own.

Cron jobs and systemd timers aren't included. Each script's own header and log path show how it's meant to be run.

## License

MIT, see `LICENSE`.
