#!/usr/bin/env python3
import datetime
import http.cookiejar
import json
import sys
import urllib.parse
import urllib.request

BASE = "http://localhost:8090"
ENV = "/etc/onepace-sync/qbit.env"
FULL = 850_000_000 // 8
CAP_UP = 37500 * 1024
CAP_DL = 62500 * 1024


def load_env():
    d = {}
    with open(ENV) as fh:
        for line in fh:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k] = v.strip().strip('"').strip("'")
    return d


def full_now(now):
    m = now.hour * 60 + now.minute
    if m < 600:
        return True
    return now.weekday() < 5 and 510 <= m < 840


def main():
    e = load_env()
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    hdr = {"Referer": BASE}

    def post(path, data):
        req = urllib.request.Request(BASE + path, urllib.parse.urlencode(data).encode(), hdr)
        return op.open(req, timeout=15).read().decode()

    def get(path):
        return op.open(urllib.request.Request(BASE + path, headers=hdr), timeout=15).read().decode()

    if post("/api/v2/auth/login", {"username": e["QB_USER"], "password": e["QB_PASS"]}).strip() == "Fails.":
        print("login failed", file=sys.stderr)
        sys.exit(1)
    now = datetime.datetime.now()
    full = full_now(now)
    up, dl = (FULL, FULL) if full else (CAP_UP, CAP_DL)
    prefs = json.loads(get("/api/v2/app/preferences"))
    want = {"scheduler_enabled": False, "up_limit": up, "dl_limit": dl}
    diff = {k: v for k, v in want.items() if prefs.get(k) != v}
    if diff:
        post("/api/v2/app/setPreferences", {"json": json.dumps(diff)})
    if get("/api/v2/transfer/speedLimitsMode").strip() == "1":
        post("/api/v2/transfer/toggleSpeedLimitsMode", {})
        diff["alt_mode_off"] = True
    if diff or "--status" in sys.argv:
        mode = "full" if full else "capped"
        print(f"{now:%Y-%m-%d %H:%M} {mode} up={up * 8 // 1_000_000}Mbit dl={dl * 8 // 1_000_000}Mbit changed={sorted(diff)}")


main()
