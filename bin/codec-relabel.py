#!/usr/bin/env python3
import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request

S = ("http://localhost:8989", "CHANGE_ME_API_KEY")
R = ("http://localhost:7878", "CHANGE_ME_API_KEY")
JF = "http://localhost:8096"
JFDB = "/home/htpc/docker/jellyfin/config/data/jellyfin.db"
STATE = "/var/lib/codec-relabel"
APPLY = "--apply" in sys.argv
LIMIT = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--limit=")), None)
VERBOSE = "--verbose" in sys.argv
MATCH = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--match=")), None)

TOKEN = re.compile(r"(?<![A-Za-z0-9])(x26[45]|h[ ._]?26[45]|hevc|avc|av1)(?![A-Za-z0-9])", re.I)
NAME_TOKEN = re.compile(r"(?<![A-Za-z0-9])(HEVC|H\.264|H\.265|x26[45]|AV1)(?![A-Za-z0-9])")
NORM = {"x265": "x265", "x264": "x264", "h265": "H.265", "h264": "H.264", "avc": "H.264", "hevc": "HEVC", "av1": "AV1"}
FAMILY = {"x265": "hevc", "H.265": "hevc", "HEVC": "hevc", "x264": "h264", "H.264": "h264", "AV1": "av1"}
GENERIC = {"hevc": "HEVC", "h264": "H.264", "av1": "AV1"}


def call(base, key, method, path, params=None, body=None, jf=False):
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    hdr = {"Content-Type": "application/json"}
    if jf:
        hdr["Authorization"] = f'MediaBrowser Token="{key}"'
    else:
        hdr["X-Api-Key"] = key
    data = json.dumps(body).encode() if body is not None else None
    raw = urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=hdr), timeout=120).read()
    return json.loads(raw) if raw else None


def mounts(name):
    m = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]["Mounts"]
    return [(x["Destination"].rstrip("/"), x["Source"].rstrip("/")) for x in m]


def to_host(mp, p):
    for d, s in sorted(mp, key=lambda t: -len(t[0])):
        if p == d or p.startswith(d + "/"):
            return s + p[len(d):]
    return None


def to_cont(mp, hp):
    for d, s in sorted(mp, key=lambda t: -len(t[1])):
        if hp == s or hp.startswith(s + "/"):
            return d + hp[len(s):]
    return None


def norm(tok):
    return NORM.get(re.sub(r"[ ._]", "", tok.lower()))


def orig_token(title):
    m = TOKEN.search(title or "")
    return norm(m.group(1)) if m else None


def sniff(hp):
    try:
        with open(hp, "rb") as fh:
            b = fh.read(32 * 1024 * 1024)
    except OSError:
        return "unreadable"
    if b"x265 (build" in b:
        return "x265"
    if b"x264 - core" in b:
        return "x264"
    return "none"


def decide(codec, ours, orig, sniffed):
    fam = {"hevc": "hevc", "h264": "h264", "av1": "av1"}.get(codec)
    if not fam:
        return None, f"unknown codec {codec}"
    if ours and sniffed not in ("x264", "x265"):
        return GENERIC[fam], "ours (tag)"
    if orig:
        if FAMILY[orig] != fam:
            return GENERIC[fam], "ours (codec changed)"
        if orig in ("x264", "x265") and sniffed == "none":
            return GENERIC[fam], "ours (encoder gone)"
        return orig, "original"
    if sniffed in ("x264", "x265") and FAMILY[sniffed] == fam:
        return sniffed, "stream"
    return GENERIC[fam], "generic"


def relabel(fname, new):
    stem, ext = os.path.splitext(fname)
    m = re.search(r"\(([^()]*)\)\s*$", stem)
    if not m or not NAME_TOKEN.search(m.group(1)):
        return None
    inner = NAME_TOKEN.sub(new, m.group(1), count=1)
    return stem[:m.start(1)] + inner + stem[m.end(1):] + ext


def latest_imports(records, key):
    out = {}
    for h in records:
        if h.get("eventType") != "downloadFolderImported":
            continue
        k = h.get(key)
        if k is None:
            continue
        if k not in out or h.get("date", "") > out[k][0]:
            out[k] = (h.get("date", ""), h.get("sourceTitle"))
    return {k: v[1] for k, v in out.items()}


def collect():
    sm, rm = mounts("sonarr"), mounts("radarr")
    items = []
    for s in call(*S, "GET", "/api/v3/series"):
        files = call(*S, "GET", "/api/v3/episodefile", {"seriesId": s["id"]})
        if not files:
            continue
        imp = latest_imports(call(*S, "GET", "/api/v3/history/series", {"seriesId": s["id"]}), "episodeId")
        ep_of = {}
        for e in call(*S, "GET", "/api/v3/episode", {"seriesId": s["id"]}):
            if e.get("episodeFileId"):
                ep_of.setdefault(e["episodeFileId"], e["id"])
        for f in files:
            hp = to_host(sm, f["path"])
            if hp:
                items.append({"app": "sonarr", "owner": s["id"], "host": hp, "src": imp.get(ep_of.get(f["id"]))})
    for m in call(*R, "GET", "/api/v3/movie"):
        if not m.get("hasFile"):
            continue
        imp = latest_imports(call(*R, "GET", "/api/v3/history/movie", {"movieId": m["id"]}), "movieId")
        for f in call(*R, "GET", "/api/v3/moviefile", {"movieId": m["id"]}):
            hp = to_host(rm, f["path"])
            if hp:
                items.append({"app": "radarr", "owner": m["id"], "host": hp, "src": imp.get(m["id"])})
    return items


def probe(items):
    tm = mounts("tdarr")
    paths = [to_cont(tm, it["host"]) or "" for it in items]
    script = 'while IFS= read -r p; do [ -n "$p" ] && ffprobe -v error -print_format json -show_entries format_tags:stream=codec_name -select_streams v:0 "$p" 2>/dev/null | tr -d "\\n"; echo; done'
    out = subprocess.run(["docker", "exec", "-i", "tdarr", "sh", "-c", script], input="\n".join(paths) + "\n", capture_output=True, text=True).stdout.splitlines()
    for it, line in zip(items, out):
        try:
            j = json.loads(line) if line.strip() else {}
        except ValueError:
            j = {}
        st = j.get("streams") or [{}]
        it["codec"] = (st[0].get("codec_name") or "").lower()
        tags = (j.get("format") or {}).get("tags") or {}
        it["ours"] = any(k.upper().startswith("TDARR_LAST_ENCODER") for k in tags)


def main():
    items = collect()
    probe(items)
    reasons, changes = {}, []
    for it in items:
        orig = orig_token(it["src"])
        sn = sniff(it["host"]) if (it["ours"] or orig in ("x264", "x265") or not orig) else "skip"
        new, why = decide(it["codec"], it["ours"], orig, sn)
        reasons[why] = reasons.get(why, 0) + 1
        if not new:
            if VERBOSE:
                print(f"  [skip: {why}] {it['host']}")
            continue
        d, fn = os.path.split(it["host"])
        nf = relabel(fn, new)
        if nf is None:
            reasons["no codec block in name"] = reasons.get("no codec block in name", 0) + 1
            continue
        if nf != fn:
            changes.append({**it, "new": os.path.join(d, nf), "why": why})
    if MATCH:
        changes = [c for c in changes if MATCH.lower() in c["host"].lower()]
    print(f"files {len(items)}, to rename {len(changes)}")
    for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {v:5}  {k}")
    for c in changes[: (None if VERBOSE else 40)]:
        print(f"  [{c['why']}] {os.path.basename(c['host'])[-70:]}  ->  {NAME_TOKEN.findall(os.path.basename(c['new']))[-1:]}")
    if not APPLY:
        print("dry run, nothing changed")
        return
    if LIMIT:
        changes = changes[:LIMIT]
    apply(changes)


def apply(changes):
    os.makedirs(STATE, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    jm = mounts("jellyfin")
    con = sqlite3.connect(f"file:{JFDB}?mode=ro", uri=True)
    key = con.execute("select AccessToken from ApiKeys limit 1").fetchone()
    if not key:
        sys.exit("no Jellyfin API key found in ApiKeys")
    key = key[0]
    want = {to_cont(jm, c["host"]): to_cont(jm, c["new"]) for c in changes}
    backup = []
    for path, uid, played, pos, cnt, last, fav in con.execute(
        "select b.Path, u.UserId, u.Played, u.PlaybackPositionTicks, u.PlayCount, u.LastPlayedDate, u.IsFavorite "
        "from UserData u join BaseItems b on b.Id = u.ItemId where b.Path is not null"
    ):
        if path in want and (played or pos or fav or cnt):
            backup.append({"new": want[path], "user": uid, "played": bool(played), "pos": pos, "count": cnt, "last": last, "fav": bool(fav)})
    con.close()
    json.dump(backup, open(f"{STATE}/userdata-{ts}.json", "w"))
    print(f"backed up {len(backup)} watched/progress entries")
    log = open(f"{STATE}/renames-{ts}.tsv", "w")
    owners = {"sonarr": set(), "radarr": set()}
    for c in changes:
        d = os.path.dirname(c["host"])
        old_stem = os.path.splitext(os.path.basename(c["host"]))[0]
        new_stem = os.path.splitext(os.path.basename(c["new"]))[0]
        for f in os.listdir(d):
            if f.startswith(old_stem + "."):
                src, dst = os.path.join(d, f), os.path.join(d, new_stem + f[len(old_stem):])
                if os.path.exists(dst):
                    print(f"exists, skipped: {dst}")
                    continue
                os.rename(src, dst)
                log.write(f"{src}\t{dst}\n")
        owners[c["app"]].add(c["owner"])
    log.close()
    print(f"renamed {len(changes)} videos (plus sidecars), log {STATE}/renames-{ts}.tsv")
    for sid in owners["sonarr"]:
        call(*S, "POST", "/api/v3/command", body={"name": "RescanSeries", "seriesId": sid})
    if owners["radarr"]:
        call(*R, "POST", "/api/v3/command", body={"name": "RescanMovie", "movieIds": sorted(owners["radarr"])})
    call(JF, key, "POST", "/Library/Refresh", jf=True)
    targets = {b["new"] for b in backup}
    deadline = time.time() + 2400
    while targets and time.time() < deadline:
        time.sleep(30)
        con = sqlite3.connect(f"file:{JFDB}?mode=ro", uri=True)
        have = {r[0] for r in con.execute("select Path from BaseItems where Path is not null")}
        con.close()
        missing = targets - have
        print(f"waiting for Jellyfin: {len(missing)} of {len(targets)} paths not indexed yet", flush=True)
        if not missing:
            break
    con = sqlite3.connect(f"file:{JFDB}?mode=ro", uri=True)
    ids = {p: i for i, p in con.execute("select Id, Path from BaseItems where Path is not null")}
    cur = {(r[0], r[1]): r[2] for r in con.execute("select ItemId, UserId, Played from UserData")}
    con.close()
    restored = skipped = failed = 0
    for b in backup:
        iid = ids.get(b["new"])
        if not iid:
            failed += 1
            continue
        if cur.get((iid, b["user"])) == int(b["played"]) and not b["pos"]:
            skipped += 1
            continue
        try:
            call(JF, key, "POST", f"/UserItems/{iid}/UserData", {"userId": b["user"]},
                 {"Played": b["played"], "PlaybackPositionTicks": b["pos"], "PlayCount": b["count"], "LastPlayedDate": b["last"], "IsFavorite": b["fav"]}, jf=True)
            restored += 1
        except Exception as e:
            failed += 1
            print(f"restore failed {b['new']}: {e}")
    print(f"watched data: restored {restored}, already intact {skipped}, failed {failed}")


main()
