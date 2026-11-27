#!/usr/bin/env python3
import datetime, json, os, re, shutil, sys, urllib.request
APPLY = "--apply" in sys.argv
HASH = os.environ.get("ONEPACE_HASH") or sys.exit("set ONEPACE_HASH to the infohash of the batch torrent")
QB = "http://localhost:8090/api/v2"
HOST_SAVE = "/mnt/4tbhdd/downloads/manual"
LIB = "/mnt/4tbhdd/anime/One Pace"
QDIR = f"/mnt/4tbhdd/.orphan_quarantine/onepace-{datetime.date.today()}"
ck = ["=".join(l.rstrip("\n").split("\t")[5:7]) for l in open("/tmp/qb.cookie") if "SID" in l and l.count("\t") >= 6][0]
def qb(path):
    return json.load(urllib.request.urlopen(urllib.request.Request(f"{QB}/{path}", headers={"Cookie": ck})))
info = qb(f"torrents/info?hashes={HASH}")[0]
files = [f["name"] for f in qb(f"torrents/files?hash={HASH}") if f["priority"] > 0]
if APPLY and (info["progress"] < 1 or info["state"].startswith(("moving", "checking"))):
    sys.exit(f"torrent at {info['progress']*100:.1f}%, state {info['state']}, not ready")
seasons = {}
for d in os.listdir(LIB):
    m = re.search(r"Season (\d+)", d)
    if m and os.path.isdir(os.path.join(LIB, d)):
        seasons[int(m.group(1))] = d
plan, extended, new_eps = [], [], {}
for n in sorted(files):
    m = re.search(r"S(\d+)E(\d+)", os.path.basename(n))
    if not m:
        print("UNPARSED", n)
        continue
    s, e = int(m.group(1)), int(m.group(2))
    if "Extended" in n:
        extended.append(n)
        continue
    new_eps.setdefault(s, set()).add(e)
    sdir = seasons.get(s, f"One Pace - Season {s:02d} - " + {1: "Romance Dawn", 2: "Orange Town", 3: "Syrup Village", 4: "Gaimon", 5: "Baratie"}.get(s, "Arc"))
    tag = f" - S{s:02d}E{e:02d} - "
    sp = os.path.join(LIB, sdir)
    qp = os.path.join(QDIR, sdir)
    names = (os.listdir(sp) if os.path.isdir(sp) else []) + (os.listdir(qp) if os.path.isdir(qp) else [])
    nfo_stems = {f[:-4] for f in names if tag in f and f.endswith(".nfo")}
    mkv_stems = sorted(f[:-4] for f in names if tag in f and f.endswith(".mkv"))
    nfos = [m for m in mkv_stems if m in nfo_stems] or mkv_stems or sorted(nfo_stems)
    target = nfos[0] + ".mkv" if nfos else f"One Pace - S{s:02d}E{e:02d}.mkv"
    plan.append((os.path.join(HOST_SAVE, n), os.path.join(LIB, sdir, target), bool(nfos)))
old = []
for s, d in sorted(seasons.items()):
    sp = os.path.join(LIB, d)
    old_nfo_eps = {int(m.group(1)) for f in os.listdir(sp) if f.endswith(".nfo") for m in [re.search(r" - S\d+E(\d+) - ", f)] if m}
    vids = [f for f in os.listdir(sp) if f.endswith(".mkv") or f.endswith(".trickplay")]
    old += [(os.path.join(sp, f), os.path.join(QDIR, d, f)) for f in vids]
    ne = new_eps.get(s, set())
    flag = "" if old_nfo_eps <= ne else f"  NFO_WITHOUT_NEW_VIDEO {sorted(old_nfo_eps - ne)}"
    print(f"S{s:02d} new={len(ne)} old_nfo={len(old_nfo_eps)} old_videos={len([v for v in vids if v.endswith('.mkv')])}{flag}")
for s in sorted(set(new_eps) - set(seasons)):
    print(f"S{s:02d} new={len(new_eps[s])} NO_LIBRARY_FOLDER")
print(f"\nlink with nfo name: {sum(p[2] for p in plan)}  plain name: {sum(not p[2] for p in plan)}  extended skipped: {len(extended)}  old to quarantine: {len(old)}")
for p in [p for p in plan if "S06E" in p[0] or "S35E01." in p[0]][:11]:
    print("EX", os.path.basename(p[0]), "->", os.path.basename(p[1]))
if not APPLY:
    print("\ndry run, add --apply to execute")
    sys.exit()
missing = [p[0] for p in plan if not os.path.exists(p[0])]
if missing:
    sys.exit(f"{len(missing)} source files missing, first: {missing[0]}")
for src, dst in old:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
for src, dst, _ in plan:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.link(src, dst)
os.system(f"chown -R htpc:htpc '{LIB}' '{QDIR}'")
print("applied, old files in", QDIR)
