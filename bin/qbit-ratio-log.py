#!/usr/bin/env python3
import json, os, time, urllib.request, urllib.parse, http.cookiejar

U = "http://localhost:8090"
QB_ENV = "/etc/onepace-sync/qbit.env"
DIR = "/var/lib/qbit-ratio-log"
DB = DIR + "/history.json"
TOP = DIR + "/top.txt"

def load_env(path):
    env = {}
    for l in open(path):
        l = l.strip()
        if "=" in l and not l.startswith("#"):
            k, v = l.split("=", 1)
            env[k.strip()] = v.strip().strip("\"'")
    return env

def write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)

env = load_env(QB_ENV)
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
op.addheaders = [("Referer", U)]
op.open(U + "/api/v2/auth/login", urllib.parse.urlencode({"username": env["QB_USER"], "password": env["QB_PASS"]}).encode(), timeout=60)
torrents = json.load(op.open(U + "/api/v2/torrents/info", timeout=60))

os.makedirs(DIR, exist_ok=True)
try:
    h = json.load(open(DB))
except Exception:
    h = {}
now = int(time.time())
seen = set()
for t in torrents:
    seen.add(t["hash"])
    e = h.get(t["hash"], {"first_seen": now})
    host = urllib.parse.urlparse(t["tracker"]).hostname
    e.update(
        name=t["name"],
        category=t["category"],
        tracker=host or e.get("tracker", "-"),
        size=t["size"],
        uploaded=max(t["uploaded"], e.get("uploaded", 0)),
        downloaded=t["downloaded"],
        ratio=t["ratio"],
        added_on=t["added_on"],
        seeding_time=t.get("seeding_time", 0),
        last_seen=now,
        removed=False,
    )
    e.pop("removed_at", None)
    h[t["hash"]] = e
for k, e in h.items():
    if k not in seen and not e.get("removed"):
        e["removed"] = True
        e["removed_at"] = now
write(DB, json.dumps(h))

lines = ["Updated " + time.strftime("%Y-%m-%d %H:%M") + f" | tracking {len(h)} torrents ({sum(1 for e in h.values() if e.get('removed'))} removed)", ""]
def table(title, key):
    lines.append(title)
    for i, e in enumerate(sorted(h.values(), key=lambda e: e[key], reverse=True)[:50], 1):
        st = "removed " + time.strftime("%Y-%m-%d", time.localtime(e["removed_at"])) if e.get("removed") else "active"
        lines.append(f'{i:2}. {e["ratio"]:8.2f} | {e["uploaded"]/1024**3:9.2f} GiB up | {e["category"][:14]:14} | {e["tracker"][:26]:26} | {st:18} | {e["name"][:60]}')
    lines.append("")
table("Top 50 by ratio", "ratio")
table("Top 50 by uploaded", "uploaded")
write(TOP, "\n".join(lines) + "\n")
