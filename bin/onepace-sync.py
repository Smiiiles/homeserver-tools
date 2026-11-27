#!/usr/bin/env python3
import email.utils, glob, http.cookiejar, json, os, re, shutil, subprocess, sys, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
RSS = "https://onepace.net/en/releases/rss.xml"
LIB = "/mnt/4tbhdd/anime/One Pace"
SINCE = datetime.fromisoformat(os.environ.get("SINCE", "2026-01-13T00:00:00+00:00"))
QB = os.environ.get("QB_URL", "http://localhost:8090")
QB_SAVE = "/4tbhdd/downloads/onepace"
STATE = "/var/lib/onepace-sync/state.json"
QUAR = "/mnt/4tbhdd/.onepace_quarantine"
APPLY = os.environ.get("APPLY") == "1"
ALIASES = {
    "trialsofkobyandhelmeppo": "trialsofkobymeppo",
    "trialsofkobymeppo": "trialsofkobymeppo",
    "adventureofstrawhats": "adventuresofstrawhats",
    "postmarineford": "postwar",
    "water7": "waterseven",
}
def norm(s):
    s = re.sub(r"\bthe\b", "", s.lower()).replace("&", "and")
    s = re.sub(r"[^a-z0-9]", "", s)
    return ALIASES.get(s, s)
def langs(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream_tags=language", "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    return set(out.split())
def txt(el, tag):
    return el.findtext("{*}" + tag) or ""
def now():
    return datetime.now().isoformat(timespec="seconds")
def media_ok(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", p], capture_output=True, text=True)
    if r.returncode:
        return False
    j = json.loads(r.stdout)
    types = {x.get("codec_type") for x in j.get("streams", [])}
    try:
        d = float(j.get("format", {}).get("duration", 0))
    except ValueError:
        d = 0
    return "video" in types and "audio" in types and d > 60
def plan():
    seasons = {}
    for d in os.listdir(LIB):
        m = re.match(r"One Pace - Season (\d+) - (.+)$", d)
        if m:
            seasons[norm(m.group(2))] = (int(m.group(1)), os.path.join(LIB, d))
    req = urllib.request.Request(RSS, headers={"User-Agent": "Mozilla/5.0 onepace-sync/1.0"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=60).read())
    best, unmapped = {}, set()
    for it in root.iterfind(".//{*}item"):
        title = txt(it, "title")
        cats = [c.text or "" for c in it.findall("{*}category")]
        when = email.utils.parsedate_to_datetime(txt(it, "pubDate"))
        if "cut/extended" in cats or "Extended" in title or "outdated" in cats or when < SINCE:
            continue
        m = re.match(r"\[One Pace\]\[[^\]]*\] (.+?) (\d{1,3}) \[\d+p\]", title)
        if not m:
            continue
        arc, ep = m.group(1), int(m.group(2))
        key = norm(arc)
        if key not in seasons:
            unmapped.add(arc)
            continue
        desc = txt(it, "description")
        am = re.search(r"<dt>Audio tracks</dt>\s*<dd>(.*?)</dd>", desc, re.S)
        if not am or "en" not in set(re.findall(r"\b([a-z]{2})\b", am.group(1))):
            continue
        season, folder = seasons[key]
        k = (season, ep)
        if k in best and best[k]["when"] >= when:
            continue
        enc = it.find("{*}enclosure")
        best[k] = {
            "arc": arc, "ep": ep, "when": when, "folder": folder,
            "hash": txt(it, "infoHash").lower(),
            "torrent": enc.get("url") if enc is not None else None,
            "review": "split into" in desc.lower(),
        }
    return best, unmapped
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def qb(path, data=None, query=None):
    url = QB + "/api/v2/" + path + ("?" + urllib.parse.urlencode(query) if query else "")
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Referer": QB})
    with opener.open(req, timeout=30) as r:
        return r.read().decode()
st = json.load(open(STATE)) if os.path.exists(STATE) else {}
best, unmapped = plan()
for (s, e), r in sorted(best.items()):
    if r["hash"] in st:
        continue
    ex = sorted(glob.glob(os.path.join(glob.escape(r["folder"]), f"*S{s:02d}E{e:02d}*.mkv")))
    what = f"replace (had dub: {'yes' if 'eng' in langs(ex[0]) else 'NO'}) {os.path.basename(ex[0])}" if ex else "NEW"
    flag = "  << REVIEW: arc was re-split" if r["review"] else ""
    print(f"PLAN S{s:02d}E{e:02d} {r['arc']} {r['ep']:02d} [{r['when']:%Y-%m-%d}] -> {what}{flag}")
if unmapped:
    print("unmapped arcs:", ", ".join(sorted(unmapped)))
if not APPLY:
    sys.exit("dry run, set APPLY=1 to add torrents and place finished downloads")
if qb("auth/login", {"username": os.environ["QB_USER"], "password": os.environ["QB_PASS"]}).strip() not in ("Ok.", "") or not any("SID" in c.name for c in jar):
    sys.exit("qBittorrent login failed")
try:
    qb("torrents/createCategory", {"category": "onepace", "savePath": QB_SAVE})
except urllib.error.HTTPError as ex:
    if ex.code != 409:
        raise
for (s, e), r in sorted(best.items()):
    if r["hash"] in st or not r["torrent"]:
        continue
    qb("torrents/add", {"urls": r["torrent"], "category": "onepace", "tags": f"onepace,S{s:02d}E{e:02d}"})
    st[r["hash"]] = {"season": s, "ep": e, "arc": r["arc"], "folder": r["folder"], "review": r["review"], "status": "added", "added": now()}
    print(f"ADDED S{s:02d}E{e:02d} {r['arc']} {e:02d}")
json.dump(st, open(STATE, "w"), indent=1)
for t in json.loads(qb("torrents/info", query={"category": "onepace"})):
    h = t["hash"].lower()
    rec = st.get(h)
    if not rec or rec["status"] != "added" or t["progress"] < 1 or t["state"] in ("moving", "checkingUP", "checkingResumeData", "missingFiles", "error"):
        continue
    src = t["content_path"].replace("/4tbhdd/", "/mnt/4tbhdd/", 1)
    if not src.endswith(".mkv") or not src.startswith("/mnt/4tbhdd/") or not os.path.isfile(src):
        print(f"WARN {h}: unexpected content path {t['content_path']}")
        continue
    s, e, folder = rec["season"], rec["ep"], rec["folder"]
    tag = f"S{s:02d}E{e:02d}"
    old = sorted(glob.glob(os.path.join(glob.escape(folder), f"One Pace - {tag} - *")))
    title = None
    for f in old:
        m = re.search(r" - S\d+E\d+ - (.*) \([^()]*\)\.mkv$", os.path.basename(f))
        if m:
            title = re.sub(r" \(Muhn Pace\)$", "", m.group(1))
    if rec["review"] or not title:
        title = f"{rec['arc']} {e:02d}"
    dest = os.path.join(folder, f"One Pace - {tag} - {title.replace('/', '-')} (1080p).mkv")
    if not media_ok(src):
        rec["status"] = "badfile"
        print(f"WARN {tag}: new file failed ffprobe check, old files left in place")
        continue
    kept = 0
    qdir = os.path.join(QUAR, datetime.now().strftime("%Y-%m-%d"), os.path.basename(folder))
    for f in old:
        if os.path.isdir(f):
            shutil.rmtree(f)
        elif f.lower().endswith((".mkv", ".mp4")) and "eng" in langs(f):
            os.makedirs(qdir, exist_ok=True)
            shutil.move(f, os.path.join(qdir, os.path.basename(f)))
            kept += 1
        else:
            os.remove(f)
    os.link(src, dest)
    fs = os.stat(folder)
    os.chown(dest, fs.st_uid, fs.st_gid)
    rec.update(status="placed", dest=dest, placed=now())
    print(f"PLACED {tag} -> {os.path.basename(dest)} (quarantined {kept} dubbed old files)")
    for oh, orec in st.items():
        if oh != h and orec.get("season") == s and orec.get("ep") == e and orec.get("status") == "placed":
            qb("torrents/delete", {"hashes": oh, "deleteFiles": "true"})
            orec["status"] = "superseded"
            print(f"REMOVED superseded torrent for {tag}")
json.dump(st, open(STATE, "w"), indent=1)
if os.path.isdir(QUAR):
    cutoff = datetime.now() - timedelta(days=7)
    for d in os.listdir(QUAR):
        try:
            if datetime.strptime(d, "%Y-%m-%d") < cutoff:
                shutil.rmtree(os.path.join(QUAR, d))
                print(f"PURGED quarantine {d}")
        except ValueError:
            pass
from collections import Counter
c = Counter(r["status"] for r in st.values())
waiting = sorted(f"S{r['season']:02d}E{r['ep']:02d}" for r in st.values() if r["status"] == "added")
print(f"SUMMARY placed {c['placed']}/{len(st)} | waiting {c['added']} | superseded {c['superseded']}")
if waiting:
    print("waiting:", " ".join(waiting))
