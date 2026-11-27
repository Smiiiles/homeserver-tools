#!/bin/bash
stamp=/var/lib/gpu-reset-watchdog.last
journalctl -k -f -n0 -o cat | while read -r line; do
  case "$line" in
    *"VRAM is lost due to GPU reset"*)
      now=$(date +%s)
      if [ -f "$stamp" ] && [ $(( now - $(stat -c %Y "$stamp") )) -lt 1800 ]; then
        logger -t gpu-reset-watchdog "GPU reset detected but a reboot happened under 30 min ago, not rebooting"
        continue
      fi
      date > "$stamp"
      logger -t gpu-reset-watchdog "GPU reset lost VRAM, rebooting in 60 seconds"
      sleep 60
      systemctl reboot
      ;;
  esac
done
