#!/usr/bin/env python3
import argparse, http.cookiejar, json, os, sys, time, urllib.parse, urllib.request

ENV = "/etc/onepace-sync/qbit.env"
STATE = "/var/lib/qbit-missing-reaper/state.json"
MOUNTS = ["/mnt/1tbhdd", "/mnt/4tbhdd"]
SKIP_CATEGORIES = {"keep"}
DATA_PREFIXES = ("/downloads/", "/1tbhdd/downloads/", "/4tbhdd/downloads/")
GRACE = 6 * 3600
MAX_MISSING = 10


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def load_env():
    cfg = {}
    with open(ENV) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip().removeprefix("export ").strip().upper()] = v.strip().strip("'\"")

    def pick(*words):
        return next((v for k, v in cfg.items() if any(w in k for w in words)), None)

    url = pick("URL", "HOST") or "http://localhost:8090"
    if not url.startswith("http"):
        url = "http://" + url
    return url.rstrip("/"), pick("USER"), pick("PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-grace", action="store_true")
    a = ap.parse_args()

    for m in MOUNTS:
        if not os.path.ismount(m):
            log(f"abort: {m} not mounted")
            return 1

    url, user, pw = load_env()
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [("Referer", url)]

    def post(path, data):
        return op.open(url + path, urllib.parse.urlencode(data).encode(), timeout=30).read()

    post("/api/v2/auth/login", {"username": user, "password": pw})
    if not any("SID" in c.name for c in jar):
        log("abort: qBittorrent login failed")
        return 1

    torrents = json.loads(op.open(url + "/api/v2/torrents/info", timeout=60).read())
    missing = [t for t in torrents if t["state"] == "missingFiles" and t.get("category") not in SKIP_CATEGORIES]
    live_paths = {t.get("content_path") for t in torrents if t["state"] != "missingFiles"}

    if len(missing) > MAX_MISSING:
        log(f"abort: {len(missing)} torrents missingFiles, over cap {MAX_MISSING}, likely mount problem")
        return 1

    try:
        with open(STATE) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    hashes = {t["hash"] for t in missing}
    state = {h: ts for h, ts in state.items() if h in hashes}
    now = time.time()

    for t in missing:
        first = state.setdefault(t["hash"], now)
        age = now - first
        if not a.no_grace and age < GRACE:
            log(f"wait {age / 3600:.1f}h: {t['name']} [{t.get('category')}]")
            continue
        path = t.get("content_path", "")
        files = path.startswith(DATA_PREFIXES) and path not in live_paths
        verb = "would delete" if a.dry_run else "delete"
        log(f"{verb} (files={files}): {t['name']} [{t.get('category')}] {t.get('tracker')} {path}")
        if not a.dry_run:
            post("/api/v2/torrents/delete", {"hashes": t["hash"], "deleteFiles": str(files).lower()})
            state.pop(t["hash"], None)

    if not missing:
        log("nothing missing")
    if not a.dry_run:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as f:
            json.dump(state, f)
    return 0


sys.exit(main())
