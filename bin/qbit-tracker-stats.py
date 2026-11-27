#!/usr/bin/env python3
import collections
import http.cookiejar
import json
import sys
import urllib.parse
import urllib.request

BASE = "http://localhost:8090"
ENV = "/etc/onepace-sync/qbit.env"
SEED = {"uploading", "stalledUP", "forcedUP", "queuedUP", "checkingUP"}


def load_env():
    d = {}
    with open(ENV) as fh:
        for line in fh:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k] = v.strip().strip('"').strip("'")
    return d


def main():
    e = load_env()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    hdr = {"Referer": BASE}
    req = urllib.request.Request(BASE + "/api/v2/auth/login", urllib.parse.urlencode({"username": e["QB_USER"], "password": e["QB_PASS"]}).encode(), hdr)
    op.open(req, timeout=15).read()
    torrents = json.loads(op.open(urllib.request.Request(BASE + "/api/v2/torrents/info", headers=hdr), timeout=60).read())
    want = sys.argv[1] if len(sys.argv) > 1 else None
    stats = collections.defaultdict(lambda: {"n": 0, "seed": 0, "partial": 0, "size": 0, "up": 0, "cats": collections.Counter()})
    for t in torrents:
        h = urllib.parse.urlparse(t.get("tracker") or "").hostname or "-"
        h = ".".join(h.split(".")[-2:])
        if want:
            if want in h:
                print(f"{t['progress'] * 100:5.1f}% {t['state']:11} {t['num_complete']:4}s {t['uploaded'] / 2**30:6.2f}G up {t['size'] / 2**30:6.2f}G {t['category']:10} {t['name'][:70]}")
            continue
        s = stats[h]
        s["n"] += 1
        s["seed"] += t["state"] in SEED
        s["partial"] += t["progress"] < 1
        s["size"] += t["size"]
        s["up"] += t["uploaded"]
        s["cats"][t["category"] or "-"] += 1
    if want:
        return
    print(f"{'tracker':22} {'n':>5} {'seed':>5} {'part':>5} {'sizeG':>8} {'upG':>8}  categories")
    for h, s in sorted(stats.items(), key=lambda x: -x[1]["n"]):
        cats = ", ".join(f"{c} {n}" for c, n in s["cats"].most_common(4))
        print(f"{h:22} {s['n']:5} {s['seed']:5} {s['partial']:5} {s['size'] / 2**30:8.1f} {s['up'] / 2**30:8.1f}  {cats}")


main()
