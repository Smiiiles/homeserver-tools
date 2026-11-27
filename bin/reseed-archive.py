#!/usr/bin/env python3
import fcntl, hashlib, http.cookiejar, json, os, re, shutil, smtplib, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from email.message import EmailMessage

BASE = "/var/lib/reseed"
DB = BASE + "/db.json"
LOG = "/var/log/reseed-archive.log"
LOCK = "/run/reseed-archive.lock"
QB = "http://localhost:8090"
QB_ENV = "/etc/onepace-sync/qbit.env"
SMTP_ENV = "/etc/homeserver-tools/smtp.env"
ARRS = {"sonarr": "http://localhost:8989", "radarr": "http://localhost:7878"}
MAP = [("/downloads", "/mnt/1tbhdd/downloads"), ("/1tbhdd", "/mnt/1tbhdd"), ("/4tbhdd", "/mnt/4tbhdd"), ("/nvme", "/mnt/nvme"), ("/ssd", "/mnt/ssd")]
SMALL_ROOTS = ["/mnt/1tbhdd", "/mnt/4tbhdd"]
SMALL = 20 * 1024 * 1024
SMALL_TOTAL = 64 * 1024 * 1024
FETCH_TIMEOUT = 24 * 3600
PATCH_MIN = 2 * 1024 * 1024
PATCH_FRAC = 0.005
MAX_PATCHES = 10
PATCH_CACHE = {}
DRY = "--dry-run" in sys.argv


def log(m):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + ("[dry] " if DRY else "") + m
    print(line)
    if not DRY:
        with open(LOG, "a") as f:
            f.write(line + "\n")


def load_env(p):
    d = {}
    with open(p) as f:
        for l in f:
            l = l.strip()
            if "=" in l and not l.startswith("#"):
                k, v = l.split("=", 1)
                d[k.strip().removeprefix("export ").strip().upper()] = v.strip().strip("'\"")
    return d


def mail(subject, body):
    if DRY:
        log("would mail: " + subject)
        return
    try:
        d = load_env(SMTP_ENV)

        def pick(*keys, default=None):
            for k in keys:
                if d.get(k):
                    return d[k]
            return default

        user = pick("SMTP_USER", "SMTP_USERNAME", "GMAIL_USER", "MAIL_USER", "USER", "USERNAME", "SMTP_FROM", "MAIL_FROM", "FROM")
        m = EmailMessage()
        m["Subject"] = subject
        m["From"] = pick("SMTP_FROM", "MAIL_FROM", "FROM", default=user)
        m["To"] = pick("MAIL_TO", "SMTP_TO", "TO", "RECIPIENT", default="you@example.com")
        m.set_content(body)
        with smtplib.SMTP(pick("SMTP_HOST", "SMTP_SERVER", "HOST", "SERVER", default="smtp.gmail.com"), int(pick("SMTP_PORT", "PORT", default="587")), timeout=30) as s:
            s.starttls()
            s.login(user, pick("SMTP_PASS", "SMTP_PASSWORD", "GMAIL_APP_PASSWORD", "APP_PASSWORD", "MAIL_PASS", "MAIL_PASSWORD", "PASSWORD", "PASS"))
            s.send_message(m)
        log("mail sent: " + subject)
    except Exception as e:
        log(f"mail failed: {e}")


def host(p):
    for a, b in MAP:
        if p == a or p.startswith(a + "/"):
            return b + p[len(a):]
    return p


def key(st):
    return f"{st.st_dev}:{st.st_ino}"


def stat(p):
    try:
        return os.stat(p)
    except OSError:
        return None


def fingerprint(p):
    h = hashlib.sha1()
    size = os.path.getsize(p)
    with open(p, "rb") as f:
        h.update(f.read(1 << 20))
        f.seek(max(0, size - (1 << 20)))
        h.update(f.read(1 << 20))
    return f"{size}:{h.hexdigest()}"


def samples_equal(a, b):
    sa, sb = os.path.getsize(a), os.path.getsize(b)
    if abs(sa - sb) > max(sa, sb) * 0.01:
        return False
    n = min(sa, sb)
    with open(a, "rb") as fa, open(b, "rb") as fb:
        for frac in (0.1, 0.5, 0.9):
            off = int(n * frac)
            fa.seek(off)
            fb.seek(off)
            if fa.read(65536) != fb.read(65536):
                return False
    return True


def small_dir(src, h):
    for r in SMALL_ROOTS:
        if src.startswith(r + "/"):
            return f"{r}/.reseed-files/{h}"
    return f"{BASE}/files/{h}"


def archive_small(src, h, idx):
    d = small_dir(src, h)
    dst = f"{d}/{idx}"
    if DRY:
        return dst
    os.makedirs(d, exist_ok=True)
    if not os.path.exists(dst):
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    return dst


class QBit:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.addheaders = [("Referer", QB)]
        e = load_env(QB_ENV)
        u = next((v for k, v in e.items() if "USER" in k), "")
        p = next((v for k, v in e.items() if "PASS" in k), "")
        try:
            self.op.open(QB + "/api/v2/auth/login", urllib.parse.urlencode({"username": u, "password": p}).encode(), timeout=30).read()
        except Exception:
            pass

    def get(self, path, raw=False):
        r = self.op.open(QB + path, timeout=120).read()
        return r if raw else json.loads(r)

    def post(self, path, data):
        return self.op.open(QB + path, urllib.parse.urlencode(data).encode(), timeout=120).read()


ARR_KEYS = {}


def arr_get(name, path):
    if name not in ARR_KEYS:
        xml = subprocess.run(["docker", "exec", name, "cat", "/config/config.xml"], capture_output=True, text=True, timeout=30).stdout
        ARR_KEYS[name] = re.search(r"<ApiKey>(.*?)</ApiKey>", xml).group(1)
    req = urllib.request.Request(ARRS[name] + path, headers={"X-Api-Key": ARR_KEYS[name]})
    return json.load(urllib.request.urlopen(req, timeout=120))


def history(name):
    out, page = [], 1
    while True:
        j = arr_get(name, f"/api/v3/history?eventType=3&pageSize=1000&page={page}&sortKey=date&sortDirection=descending")
        recs = j.get("records", [])
        out += recs
        if len(recs) < 1000:
            return out
        page += 1


def resolve_lib(fe):
    try:
        if fe.get("arr") == "sonarr" and fe.get("fileId"):
            return host(arr_get("sonarr", f"/api/v3/episodefile/{fe['fileId']}")["path"])
        if fe.get("arr") == "radarr" and fe.get("movieId"):
            files = arr_get("radarr", f"/api/v3/moviefile?movieId={fe['movieId']}")
            if files:
                return host(files[0]["path"])
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return None


def make_patch(lib, orig, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    subprocess.run(["xdelta3", "-e", "-f", "-B", "268435456", "-s", lib, orig, tmp], check=True, timeout=14400)
    size = os.path.getsize(tmp)
    if size > max(PATCH_MIN, os.path.getsize(orig) * PATCH_FRAC):
        os.remove(tmp)
        return None
    dec = subprocess.Popen(["xdelta3", "-d", "-c", "-s", lib, tmp], stdout=subprocess.PIPE)
    ok = subprocess.run(["cmp", "-s", "-", orig], stdin=dec.stdout, timeout=14400).returncode == 0
    dec.stdout.close()
    if dec.wait() != 0 or not ok:
        os.remove(tmp)
        return None
    os.replace(tmp, out)
    return size


def drop(h, e, reason):
    log(f"unrestorable: {e['name']} ({reason})")
    if not DRY:
        p = f"{BASE}/torrents/{h}.torrent"
        if os.path.exists(p):
            os.remove(p)
        shutil.rmtree(f"{BASE}/patches/{h}", ignore_errors=True)
        shutil.rmtree(f"{BASE}/files/{h}", ignore_errors=True)
        for r in SMALL_ROOTS:
            shutil.rmtree(f"{r}/.reseed-files/{h}", ignore_errors=True)
    e.update(status="unrestorable", reason=reason, files={}, ended=int(time.time()))


def process_active(qb, t, e, idx, budget):
    h = t["hash"]
    tfile = f"{BASE}/torrents/{h}.torrent"
    if not os.path.exists(tfile) and not DRY:
        blob = qb.get(f"/api/v2/torrents/export?hash={h}", raw=True)
        with open(tfile, "wb") as f:
            f.write(blob)
    files = qb.get(f"/api/v2/torrents/files?hash={h}")
    small_total = sum(f["size"] for f in files if f["size"] <= SMALL)
    if any(f.get("priority", 1) == 0 and f["size"] > SMALL for f in files):
        return drop(h, e, "big file skipped in qBittorrent (sample)")
    now = int(time.time())
    states = []
    for f in files:
        fe = e["files"].setdefault(str(f["index"]), {"rel": f["name"], "size": f["size"]})
        src = os.path.join(host(t["save_path"]), f["name"])
        if fe.get("state") in ("copied", "patched"):
            states.append(fe["state"])
            continue
        small = f["size"] <= SMALL and small_total <= SMALL_TOTAL
        if f.get("priority", 1) == 0:
            if small and not fe.get("refetch_failed"):
                if not DRY:
                    qb.post("/api/v2/torrents/filePrio", {"hash": h, "id": str(f["index"]), "priority": "1"})
                fe.setdefault("fetch_since", now)
                log(f"re-enabled skipped file: {f['name']}")
                fe["state"] = "fetching"
                states.append("fetching")
                continue
            fe["state"] = "skipped"
            states.append("skipped")
            continue
        st = stat(src)
        if st is None or f.get("progress", 1) < 1:
            if small:
                since = fe.setdefault("fetch_since", now)
                if now - since > FETCH_TIMEOUT:
                    if not DRY:
                        qb.post("/api/v2/torrents/filePrio", {"hash": h, "id": str(f["index"]), "priority": "0"})
                    log(f"gave up fetching after 24h: {f['name']}")
                    fe.update(state="skipped", refetch_failed=True)
                    states.append("skipped")
                    continue
                fe["state"] = "fetching"
                states.append("fetching")
                continue
            fe["state"] = "missing"
            states.append("missing")
            continue
        if small:
            fe.update(state="copied", copy=archive_small(src, h, f["index"]))
            states.append("copied")
            continue
        ref = idx.get(key(st))
        if not ref:
            fe["state"] = "nolib"
            states.append("nolib")
            continue
        fe.update(arr=ref["arr"], fileId=ref.get("fileId"), movieId=ref.get("movieId"))
        lib = ref["lib"]
        lst = stat(lib)
        if lst is None:
            lib = resolve_lib(fe)
            lst = stat(lib) if lib else None
        if lst is None:
            fe["state"] = "nolib"
            states.append("nolib")
            continue
        fe["lib"] = lib
        if key(lst) == key(st):
            fp = fingerprint(src)
            if fe.get("state") == "linked" and fe.get("fp") and fe["fp"] != fp:
                log(f"ALERT in-place change of seeding data: {src}")
                mail("reseed-archive: seeding data changed in place", f"{src}\n\nTorrent: {e['name']} ({e.get('tracker')})\n\nThe library file is still the same hardlink as the seeding torrent, but its content changed. Something (likely a Tdarr mkvpropedit step) edited the torrent's data in place. Peers will get bad pieces and the torrent may fail a recheck. Force-recheck it in qBittorrent.")
            fe.update(state="linked", fp=fp)
            states.append("linked")
            continue
        if not samples_equal(lib, src):
            fe["state"] = "rewritten"
            states.append("rewritten")
            continue
        lfp = fingerprint(lib)
        cached = PATCH_CACHE.get(key(st) + "|" + lfp)
        if cached and os.path.exists(cached):
            out = f"{BASE}/patches/{h}/{f['index']}.xd3"
            if not DRY:
                os.makedirs(os.path.dirname(out), exist_ok=True)
                if cached != out:
                    shutil.copy2(cached, out)
            fe.update(state="patched", patch=out, lib_fp=lfp)
            states.append("patched")
            continue
        if budget[0] <= 0:
            fe["state"] = "pending_patch"
            states.append("pending_patch")
            continue
        budget[0] -= 1
        out = f"{BASE}/patches/{h}/{f['index']}.xd3"
        if DRY:
            log(f"would patch: {lib}")
            states.append("pending_patch")
            continue
        size = make_patch(lib, src, out)
        if size is None:
            fe["state"] = "rewritten"
            states.append("rewritten")
            continue
        log(f"patched {os.path.basename(lib)}: {size} bytes")
        fe.update(state="patched", patch=out, lib_fp=fingerprint(lib))
        PATCH_CACHE[key(st) + "|" + fe["lib_fp"]] = out
        states.append("patched")
    if "rewritten" in states:
        drop(h, e, "rewritten by Tdarr")
    elif "missing" in states:
        drop(h, e, "file not on disk")
    elif "skipped" in states:
        drop(h, e, "file skipped in qBittorrent (sample or unfetchable)")
    elif all(s in ("linked", "patched", "copied") for s in states):
        if e["status"] != "restorable":
            log(f"restorable: {e['name']}")
        e["status"] = "restorable"
    else:
        e["status"] = "pending"


def validate_removed(h, e):
    if e["status"] != "restorable":
        drop(h, e, "removed before it was archived")
        return
    for fe in e["files"].values():
        s = fe.get("state")
        if s == "copied":
            if not fe.get("copy") or not os.path.exists(fe["copy"]):
                return drop(h, e, "archived small file missing")
            continue
        lib = fe.get("lib")
        if not lib or not os.path.exists(lib):
            lib = resolve_lib(fe)
            if not lib or not os.path.exists(lib):
                return drop(h, e, "library file gone")
            fe["lib"] = lib
        fp = fingerprint(lib)
        if s == "linked" and fp != fe.get("fp"):
            return drop(h, e, "library file changed after torrent removal")
        if s == "patched" and fp != fe.get("lib_fp"):
            return drop(h, e, "library file changed after patching")


def main():
    for d in ("torrents", "patches", "files"):
        os.makedirs(f"{BASE}/{d}", exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    try:
        with open(DB) as f:
            db = json.load(f)
    except Exception:
        db = {}
    db.setdefault("t", {})
    idx = db.setdefault("inodes", {})
    PATCH_CACHE.update(db.setdefault("patch_cache", {}))
    qb = QBit()
    qb.get("/api/v2/app/version", raw=True)
    for name in ARRS:
        for r in history(name):
            d = r.get("data", {})
            ref = {"arr": name, "fileId": d.get("fileId"), "movieId": r.get("movieId"), "lib": host(d.get("importedPath", ""))}
            for p in (host(d.get("droppedPath", "")), ref["lib"]):
                st = stat(p) if p else None
                if st:
                    idx[key(st)] = ref
    torrents = qb.get("/api/v2/torrents/info")
    if not torrents:
        log("abort: empty torrent list")
        return
    in_client = {t["hash"] for t in torrents}
    budget = [MAX_PATCHES]
    for t in torrents:
        h = t["hash"]
        e = db["t"].get(h)
        if e and e["status"] == "unrestorable":
            continue
        priv = t.get("private")
        if priv is None:
            priv = qb.get(f"/api/v2/torrents/properties?hash={h}").get("is_private")
        if not priv:
            continue
        if t.get("progress", 0) < 1 and not (e and any(fe.get("state") == "fetching" for fe in e["files"].values())):
            continue
        if e is None:
            e = db["t"][h] = {"name": t["name"], "tracker": urllib.parse.urlparse(t.get("tracker", "")).hostname or "", "category": t.get("category"), "first_seen": int(time.time()), "status": "pending", "files": {}}
        e["save_path"] = t["save_path"]
        try:
            process_active(qb, t, e, idx, budget)
        except Exception as ex:
            log(f"error on {t['name']}: {ex}")
    for h, e in db["t"].items():
        if e["status"] != "unrestorable" and h not in in_client:
            try:
                validate_removed(h, e)
            except Exception as ex:
                log(f"error validating {e['name']}: {ex}")
    counts = {}
    for e in db["t"].values():
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    log("summary: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    db["patch_cache"] = PATCH_CACHE
    if not DRY:
        tmp = DB + ".tmp"
        with open(tmp, "w") as f:
            json.dump(db, f)
        os.replace(tmp, DB)


if __name__ == "__main__":
    main()
