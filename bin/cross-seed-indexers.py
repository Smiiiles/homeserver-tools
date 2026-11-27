#!/usr/bin/env python3
import json, os, re, sqlite3, subprocess, urllib.request, datetime
stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
DB = "/home/htpc/docker/cross-seed/cross-seed.db"
key = re.search(r"<ApiKey>(\w+)</ApiKey>", open("/home/htpc/docker/prowlarr/config/config.xml").read()).group(1)
req = urllib.request.Request("http://127.0.0.1:9696/api/v1/indexer", headers={"X-Api-Key": key})
idx = json.load(urllib.request.urlopen(req, timeout=30))
EXCLUDE = tuple(x.strip().lower() for x in os.environ.get("CROSS_SEED_EXCLUDE", "fallback").split(",") if x.strip())
want = {f"http://localhost:9696/{i['id']}/api": i["name"] for i in idx if i.get("enable") and i.get("protocol") == "torrent" and not any(x in i["name"].lower() for x in EXCLUDE)}
assert want, "no enabled torrent indexers"

c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
have = {u: e for u, e in c.execute("select url, enabled from indexer")}
c.close()
add = [u for u in want if u not in have]
enable = [u for u in want if u in have and not have[u]]
disable = [u for u, e in have.items() if e and u not in want]
if not (add or enable or disable):
    print(stamp, "unchanged", len(want))
    raise SystemExit(0)

subprocess.run(["docker", "stop", "cross-seed"], check=True, capture_output=True)
try:
    src = sqlite3.connect(DB)
    snap = sqlite3.connect(DB + ".pre-indexer-sync")
    src.backup(snap)
    snap.close()
    with src:
        for u in add:
            src.execute("insert into indexer (url, apikey, name, enabled) values (?, ?, ?, 1)", (u, key, want[u]))
        for u in enable:
            src.execute("update indexer set enabled = 1, apikey = ? where url = ?", (key, u))
        for u in disable:
            src.execute("update indexer set enabled = 0 where url = ?", (u,))
    src.close()
finally:
    for f in (DB, DB + "-wal", DB + "-shm", DB + ".pre-indexer-sync"):
        if os.path.exists(f):
            os.chown(f, 1001, 1001)
    subprocess.run(["docker", "start", "cross-seed"], check=True, capture_output=True)
print(stamp, f"added {[want[u] for u in add]}, enabled {[want[u] for u in enable]}, disabled {len(disable)}")
