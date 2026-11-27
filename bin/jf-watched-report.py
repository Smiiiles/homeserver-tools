#!/usr/bin/env python3
import collections
import json
import os
import sqlite3
import subprocess
import sys

DB = "/home/htpc/docker/jellyfin/config/data/jellyfin.db"
MOVIE = "MediaBrowser.Controller.Entities.Movies.Movie"
EPISODE = "MediaBrowser.Controller.Entities.TV.Episode"

mounts = json.loads(subprocess.check_output(["docker", "inspect", "jellyfin"]))[0]["Mounts"]
maps = sorted(((m["Destination"].rstrip("/"), m["Source"].rstrip("/")) for m in mounts), key=lambda x: -len(x[0]))


def host(p):
    for d, s in maps:
        if p == d or p.startswith(d + "/"):
            return s + p[len(d):]
    return p


con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
users = dict(con.execute("select Id, Username from Users"))
played = collections.defaultdict(set)
for iid, uid in con.execute("select ItemId, UserId from UserData where Played = 1"):
    played[iid].add(users.get(uid, uid))
rows = con.execute(
    "select Id, Type, Name, Path, SeriesName, ProductionYear from BaseItems "
    "where IsVirtualItem = 0 and Path is not null and Type in (?, ?)",
    (MOVIE, EPISODE),
).fetchall()
groups = {}
for iid, typ, name, path, series, year in rows:
    key = ("M", f"{name} ({year})") if typ == MOVIE else ("S", series or "?")
    try:
        st = os.stat(host(path))
    except OSError:
        continue
    g = groups.setdefault(key, {"n": 0, "size": 0, "free": 0, "pl": collections.Counter()})
    g["n"] += 1
    g["size"] += st.st_size
    if st.st_nlink == 1:
        g["free"] += st.st_size
    for u in played[iid]:
        g["pl"][u] += 1
out = sorted(((k, g) for k, g in groups.items() if g["pl"]), key=lambda x: -x[1]["size"])
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 60
print(f"{'t':1} {'sizeG':>7} {'freeG':>7} {'files':>5}  title  [watched by: files]")
for (t, title), g in out[:limit]:
    pl = ", ".join(f"{u} {c}/{g['n']}" for u, c in g["pl"].most_common())
    print(f"{t} {g['size'] / 2**30:7.1f} {g['free'] / 2**30:7.1f} {g['n']:5}  {title}  [{pl}]")
