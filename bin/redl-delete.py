#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

SONARR = ("http://localhost:8989", "CHANGE_ME_API_KEY")
RADARR = ("http://localhost:7878", "CHANGE_ME_API_KEY")
APPLY = "--apply" in sys.argv
ARGS = [a for a in sys.argv[1:] if a != "--apply"]


def call(api, method, path, params=None, body=None):
    base, key = api
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"X-Api-Key": key, "Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=120).read()
    return json.loads(raw) if raw else None


def mounts(name):
    m = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]["Mounts"]
    return sorted(((x["Destination"].rstrip("/"), x["Source"].rstrip("/")) for x in m), key=lambda t: -len(t[0]))


def host(maps, p):
    for d, s in maps:
        if p == d or p.startswith(d + "/"):
            return s + p[len(d):]
    return None


def check(maps, p):
    hp = host(maps, p)
    if not hp:
        return False, "path not mapped", 0
    try:
        st = os.stat(hp)
    except OSError:
        return False, "missing on disk", 0
    if st.st_nlink != 1:
        return False, f"{st.st_nlink} hardlinks, still seeding", st.st_size
    return True, "", st.st_size


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def do_movie(title, year):
    maps = mounts("radarr")
    hit = [m for m in call(RADARR, "GET", "/api/v3/movie") if norm(m["title"]) == norm(title) and (year is None or m.get("year") == year)]
    if not hit:
        print(f"[MISS] {title} ({year})")
        return
    m = hit[0]
    files = call(RADARR, "GET", "/api/v3/moviefile", {"movieId": m["id"]})
    results = [(f, *check(maps, f["path"])) for f in files]
    bad = [r for r in results if not r[1]]
    size = sum(r[3] for r in results)
    if not files:
        print(f"[NONE] {m['title']} ({m['year']}) has no file")
        return
    if bad:
        for f, _, why, _ in bad:
            print(f"[SKIP] {m['title']} ({m['year']}): {why}")
        return
    print(f"[{'DEL' if APPLY else 'DRY'}] {m['title']} ({m['year']}) {len(files)} file(s) {size / 2**30:.1f}G, unmonitor + delete file")
    if APPLY:
        m["monitored"] = False
        call(RADARR, "PUT", f"/api/v3/movie/{m['id']}", body=m)
        for f in files:
            call(RADARR, "DELETE", f"/api/v3/moviefile/{f['id']}")


def do_series(title):
    maps = mounts("sonarr")
    ss = call(SONARR, "GET", "/api/v3/series")
    hit = [s for s in ss if norm(s["title"]) == norm(title) or norm(f"{s['title']} {s.get('year')}") == norm(title)]
    if not hit:
        print(f"[MISS] {title}")
        return
    s = hit[0]
    files = call(SONARR, "GET", "/api/v3/episodefile", {"seriesId": s["id"]})
    ok, size = set(), 0
    for f in files:
        good, why, sz = check(maps, f["path"])
        if good:
            ok.add(f["id"])
            size += sz
        else:
            print(f"[SKIP] {s['title']} {os.path.basename(f['path'])[:70]}: {why}")
    eps = [e["id"] for e in call(SONARR, "GET", "/api/v3/episode", {"seriesId": s["id"]}) if e.get("episodeFileId") in ok]
    print(f"[{'DEL' if APPLY else 'DRY'}] {s['title']} {len(ok)}/{len(files)} file(s) {size / 2**30:.1f}G, unmonitor {len(eps)} episode(s) + delete files")
    if APPLY and ok:
        call(SONARR, "PUT", "/api/v3/episode/monitor", body={"episodeIds": eps, "monitored": False})
        call(SONARR, "DELETE", "/api/v3/episodefile/bulk", body={"episodeFileIds": sorted(ok)})


for arg in ARGS:
    kind, _, rest = arg.partition(":")
    if kind == "movie":
        t, _, y = rest.rpartition(":")
        do_movie(t, int(y)) if y.isdigit() else do_movie(rest, None)
    else:
        do_series(rest)
