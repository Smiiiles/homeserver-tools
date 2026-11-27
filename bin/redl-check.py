#!/usr/bin/env python3
import collections
import glob
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

SONARR = "http://localhost:8989"
SONARR_KEY = "CHANGE_ME_API_KEY"
RADARR = "http://localhost:7878"
RADARR_KEY = "CHANGE_ME_API_KEY"
PROWLARR = "http://localhost:9696"
RES = re.compile(r"\b(2160p|1080p|720p|480p)\b", re.I)
CODEC = re.compile(r"\b(x265|h\.?265|hevc|x264|h\.?264|avc|av1)\b", re.I)


def prowlarr_key():
    for p in glob.glob("/home/htpc/docker/prowlarr/config.xml") + glob.glob("/home/htpc/docker/prowlarr/*/config.xml"):
        m = re.search(r"<ApiKey>([^<]+)</ApiKey>", open(p).read())
        if m:
            return m.group(1)
    sys.exit("Prowlarr API key not found")


def get(base, key, path, params=None, timeout=60):
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"X-Api-Key": key})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def sonarr(path, params=None):
    for v in ("v3", "v5"):
        try:
            return get(SONARR, SONARR_KEY, f"/api/{v}{path}", params)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    sys.exit(f"Sonarr API path not found: {path}")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def codec_of(s):
    m = CODEC.search(s or "")
    if not m:
        return "?"
    c = m.group(1).lower().replace(".", "")
    if c in ("x265", "h265", "hevc"):
        return "hevc"
    if c in ("x264", "h264", "avc"):
        return "avc"
    return c


def res_of(s):
    m = RES.search(s or "")
    return m.group(1).lower() if m else "?"


PK = prowlarr_key()
PRIV = {i["id"]: i.get("privacy", "private") for i in get(PROWLARR, PK, "/api/v1/indexer")}


def search(query, cat):
    return get(PROWLARR, PK, "/api/v1/search", [("query", query), ("type", "search"), ("categories", cat), ("limit", "100")], timeout=300)


def rate(results, want):
    seen, good = set(), []
    grp = want["group"]
    for x in results:
        key = x.get("guid") or x.get("title")
        if key in seen:
            continue
        seen.add(key)
        fl = x.get("downloadVolumeFactor", 1) == 0
        if PRIV.get(x.get("indexerId")) != "public" and not fl:
            continue
        if (x.get("seeders") or 0) < 3:
            continue
        t = x.get("title", "")
        if res_of(t) != want["res"]:
            continue
        if want["codec"] != "?" and codec_of(t) not in (want["codec"], "?"):
            continue
        same = bool(grp) and (("-" + grp) in t.lower() or f"[{grp}]" in t.lower())
        good.append((same, x.get("seeders") or 0, fl, x))
    good.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return good


def want_from(f):
    name = f.get("sceneName") or f.get("relativePath") or ""
    r = (f.get("quality") or {}).get("quality", {}).get("resolution")
    return name, {"res": f"{r}p" if r else res_of(name), "codec": codec_of(name), "group": (f.get("releaseGroup") or "").lower()}


def report(label, have, want, good):
    status = "SAME" if good and good[0][0] else "EQUIV" if good else "NONE"
    print(f"[{status}] {label} | have {want['res']} {want['codec']} {want['group'] or '-'} | {have[:90]}")
    for same, seeds, fl, x in good[:3]:
        tag = "=" if same else "~"
        print(f"    {tag} {seeds:5}s {x.get('size', 0) / 2**30:6.1f}G {'FL ' if fl else ''}{x.get('indexer', '')[:16]:16} {x.get('title', '')[:95]}")
    sys.stdout.flush()


def do_movie(title, year):
    ms = get(RADARR, RADARR_KEY, "/api/v3/movie")
    hit = [m for m in ms if norm(m["title"]) == norm(title) and (year is None or m.get("year") == year)]
    if not hit:
        print(f"[MISS] movie {title} ({year}) not found in Radarr")
        return
    m = hit[0]
    f = m.get("movieFile")
    if not f and m.get("hasFile"):
        fs = get(RADARR, RADARR_KEY, "/api/v3/moviefile", {"movieId": m["id"]})
        f = fs[0] if fs else None
    if not f:
        print(f"[MISS] movie {m['title']} ({m['year']}) has no file")
        return
    name, want = want_from(f)
    report(f"{m['title']} ({m['year']})", name, want, rate(search(f"{m['title']} {m['year']}", "2000"), want))


def do_series(title):
    ss = sonarr("/series")
    hit = [s for s in ss if norm(s["title"]) == norm(title) or norm(f"{s['title']} {s.get('year')}") == norm(title)]
    if not hit:
        print(f"[MISS] series {title} not found in Sonarr")
        return
    s = hit[0]
    seasons = collections.defaultdict(list)
    for f in sonarr("/episodefile", {"seriesId": s["id"]}):
        seasons[f["seasonNumber"]].append(f)
    for sn, fs in sorted(seasons.items()):
        grp = collections.Counter((f.get("releaseGroup") or "") for f in fs).most_common(1)[0][0]
        rep = next(f for f in fs if (f.get("releaseGroup") or "") == grp)
        name, want = want_from(rep)
        label = f"{s['title']} S{sn:02d} ({len(fs)} files)"
        good = rate(search(f"{s['title']} S{sn:02d}", "5000"), want)
        if not good:
            good = rate(search(s["title"], "5000"), want)
            label += " [title-only search]"
        report(label, name, want, good)


for arg in sys.argv[1:]:
    kind, _, rest = arg.partition(":")
    if kind == "movie":
        t, _, y = rest.rpartition(":")
        if y.isdigit():
            do_movie(t, int(y))
        else:
            do_movie(rest, None)
    else:
        do_series(rest)
