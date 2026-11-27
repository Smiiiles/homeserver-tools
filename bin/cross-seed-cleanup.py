#!/usr/bin/env python3
import json, subprocess, datetime

def q(path, data=None):
    cmd = ["docker", "exec", "qbittorrent", "curl", "-s"]
    if data:
        cmd += ["--data", data]
    cmd.append(f"http://localhost:8080{path}")
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
torrents = json.loads(q("/api/v2/torrents/info?filter=all"))
dead = [t for t in torrents if t.get("state") == "missingFiles" and t.get("category", "").endswith(".cross-seed")]
if dead:
    q("/api/v2/torrents/delete", "hashes=" + "|".join(t["hash"] for t in dead) + "&deleteFiles=false")
print(stamp, f"removed {len(dead)} dead cross-seeds", [t["name"] for t in dead])
