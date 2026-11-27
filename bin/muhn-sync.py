#!/usr/bin/env python3
import glob, json, os, re, shutil, subprocess, sys
from datetime import datetime
MUHN = os.environ.get("MUHN_FOLDER_ID", "")
WP = os.environ.get("MUHN_WP_FOLDER_ID", "")
LIB = "/mnt/4tbhdd/anime/One Pace"
STAGE = "/mnt/4tbhdd/downloads/muhnpace"
QUAR = "/mnt/4tbhdd/.onepace_quarantine"
CONF = "/home/youruser/.config/rclone/rclone.conf"
APPLY = os.environ.get("APPLY") == "1"
LIMIT = int(os.environ.get("LIMIT", "0"))
ONLY = os.environ.get("ARC", "").lower()
SOURCES = [
    ("Whisky Peak (M4Rquis)", WP, "", 10, 0, False),
    ("17 - Enies Lobby", MUHN, "17 - Enies Lobby", 19, 0, False),
    ("18 - Post Enies Lobby", MUHN, "18 - Post Enies Lobby", 20, 1, False),
    ("19 - Thriller Bark", MUHN, "19 - Thriller Bark", 21, 0, False),
    ("20 - Sabaody Archipelago", MUHN, "20 - Sabaody Archipelago", 22, 0, False),
    ("21 - Amazon Lily", MUHN, "21 - Amazon Lily", 23, 0, False),
    ("22 - Impel Down", MUHN, "22 - Impel Down", 24, 0, False),
    ("23 - Marineford", MUHN, "23 - Marineford", 26, 0, False),
    ("24 - Post War", MUHN, "24 - Post War", 27, 0, False),
    ("26 - Fishman Island", MUHN, "26 - Fishman Island", 29, 0, False),
    ("27 - Punk Hazard", MUHN, "27 - Punk Hazard", 30, 0, False),
    ("28 - Dressrosa", MUHN, "28 - Dressrosa", 31, 0, False),
    ("29 - Zou", MUHN, "29 - Zou", 32, 0, False),
    ("30 - Whole Cake Island", MUHN, "30 - Whole Cake Island", 33, 0, False),
    ("32 - Wano Acts 1 & 2", MUHN, "32 - Wano Acts 1 & 2", 35, 0, False),
    ("33 - Wano Act 3", MUHN, "33 - Wano Act 3", 35, 0, True),
]
def rc(root, *args):
    return subprocess.run(["rclone", "--config", CONF, "--drive-root-folder-id", root, *args], capture_output=True, text=True)
def src(path, name=None):
    p = "/".join(x for x in (path, name) if x)
    return "gdrive:" + p
def langs(p):
    return set(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream_tags=language", "-of", "csv=p=0", p], capture_output=True, text=True).stdout.split())
def dur(p):
    try:
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True).stdout.strip())
    except ValueError:
        return 0.0
def ranges(nums):
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"E{start:02d}" if start == prev else f"E{start:02d}-E{prev:02d}")
            start = prev = n
    if start is not None:
        out.append(f"E{start:02d}" if start == prev else f"E{start:02d}-E{prev:02d}")
    return ",".join(out)
def season_dir(n):
    g = glob.glob(os.path.join(glob.escape(LIB), f"One Pace - Season {n:02d} - *"))
    return g[0] if g else None
def library(sdir):
    eps = {}
    for f in sorted(os.listdir(sdir)):
        m = re.search(r"S\d+E(\d+)", f)
        if not m or not f.lower().endswith((".mkv", ".mp4")):
            continue
        p = os.path.join(sdir, f)
        e = int(m.group(1))
        eng = "eng" in langs(p)
        if e not in eps or (eng and not eps[e][1]):
            eps[e] = (p, eng)
    return eps
plan, total = [], 0
for label, root, path, season, shift, add in SOURCES:
    if ONLY and ONLY not in label.lower():
        continue
    sdir = season_dir(season)
    if not sdir:
        print(f"ERR no library folder for season {season}")
        continue
    lib = library(sdir)
    r = rc(root, "lsjson", "--files-only", src(path))
    if r.returncode:
        print(f"ERR {label}: {r.stderr.strip()[-300:]}")
        continue
    muhn = {}
    for f in json.loads(r.stdout):
        m = re.search(r"(\d+)\s*\.(mp4|mkv)$", f["Name"], re.I)
        if m:
            muhn[int(m.group(1)) + shift] = f
    if add:
        need = [e for e in sorted(muhn) if e not in lib]
    else:
        need = [e for e in sorted(muhn) if e in lib and not lib[e][1]]
    size = sum(muhn[e]["Size"] for e in need)
    total += size
    print(f"S{season:02d} {label}: source {ranges(sorted(muhn))} | {'add' if add else 'need'} {ranges(need) or '-'} | {size / 1e9:.1f} GB")
    for e in need:
        plan.append((label, root, path, season, e, muhn[e]["Name"], lib.get(e, (None,))[0], sdir))
print(f"\n{len(plan)} episodes to fetch, {total / 1e9:.1f} GB")
if not APPLY:
    sys.exit("dry run, set APPLY=1 to download and swap (LIMIT=n and ARC=text to narrow)")
if LIMIT:
    plan = plan[:LIMIT]
today = datetime.now().strftime("%Y-%m-%d")
for label, root, path, season, e, name, old, sdir in plan:
    tag = f"S{season:02d}E{e:02d}"
    stage = os.path.join(STAGE, label)
    os.makedirs(stage, exist_ok=True)
    dst = os.path.join(stage, name)
    if not os.path.exists(dst):
        r = rc(root, "copyto", src(path, name), dst)
        if r.returncode:
            err = r.stderr.strip()[-300:]
            print(f"FAIL {tag} {name}: {err}")
            if "quota" in err.lower():
                print("STOP: Google download quota hit, rerun later")
                break
            continue
    nl = langs(dst)
    if "eng" not in nl:
        print(f"SKIP {tag}: download has no English audio ({' '.join(nl) or 'none'})")
        continue
    dn = dur(dst)
    if old:
        do = dur(old)
        if do and dn and abs(dn - do) / do > 0.15:
            print(f"MISMATCH {tag}: old {do / 60:.1f} min vs new {dn / 60:.1f} min, left in {stage}")
            continue
        m = re.search(r" - S\d+E\d+ - (.*) \([^()]*\)\.(mkv|mp4)$", os.path.basename(old))
        title = m.group(1) if m else f"{label.split(' - ')[-1]} {e:02d}"
    else:
        title = f"{label.split(' - ')[-1].split(' Act')[0]} {e:02d}"
    qdir = os.path.join(QUAR, today, os.path.basename(sdir))
    for f in glob.glob(os.path.join(glob.escape(sdir), f"One Pace - {tag} - *")):
        if os.path.isdir(f):
            shutil.rmtree(f)
        elif f.lower().endswith((".mkv", ".mp4")) and "eng" in langs(f):
            os.makedirs(qdir, exist_ok=True)
            shutil.move(f, os.path.join(qdir, os.path.basename(f)))
        else:
            os.remove(f)
    ext = os.path.splitext(name)[1].lower()
    new = os.path.join(sdir, f"One Pace - {tag} - {title} (Muhn Pace){ext}")
    shutil.move(dst, new)
    st = os.stat(sdir)
    os.chown(new, st.st_uid, st.st_gid)
    print(f"PLACED {tag} -> {os.path.basename(new)} ({dn / 60:.0f} min)")
if os.path.exists(CONF):
    h = os.stat("/home/youruser")
    os.chown(CONF, h.st_uid, h.st_gid)
