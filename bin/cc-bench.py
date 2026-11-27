#!/usr/bin/env python3
import json
import os
import statistics
import subprocess
import sys

BIN = "/usr/local/bin/speedtest-ookla"
LOCK = "/run/cc-bench"
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 2


def gpid():
    return subprocess.check_output(["docker", "inspect", "-f", "{{.State.Pid}}", "gluetun"], text=True).strip()


def setcc(cc):
    subprocess.run(["nsenter", "-t", gpid(), "-n", "sysctl", "-qw", f"net.ipv4.tcp_congestion_control={cc}"], check=True)


def ookla(*args):
    cmd = ["docker", "run", "--rm", "--network", "container:gluetun", "-v", f"{BIN}:/s:ro", "alpine", "/s", "--accept-license", "--accept-gdpr", "-f", "json", *args]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300).stdout
    for line in out.splitlines():
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def main():
    open(LOCK, "w").close()
    res = {"cubic": [], "bbr": []}
    try:
        servers = [s["id"] for s in (ookla("-L") or {}).get("servers", [])[:2]]
        if not servers:
            sys.exit("no servers found")
        for r in range(ROUNDS):
            for cc in (("cubic", "bbr") if r % 2 == 0 else ("bbr", "cubic")):
                setcc(cc)
                for sid in servers:
                    j = ookla("-s", str(sid))
                    if not j or j.get("type") != "result":
                        print(f"{cc:5} {sid}: failed", flush=True)
                        continue
                    dn = j["download"]["bandwidth"] * 8 / 1e6
                    up = j["upload"]["bandwidth"] * 8 / 1e6
                    loss = j.get("packetLoss", 0)
                    res[cc].append((dn, up))
                    print(f"{cc:5} {j['server']['name'][:22]:22} {j['server']['location'][:12]:12} down {dn:6.0f} up {up:6.0f} loss {loss:.1f}%", flush=True)
    finally:
        setcc("bbr")
        os.remove(LOCK)
    for cc, v in res.items():
        if v:
            print(f"{cc:5} median down {statistics.median(d for d, _ in v):6.0f} up {statistics.median(u for _, u in v):6.0f}  ({len(v)} runs)")


main()
