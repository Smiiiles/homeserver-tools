#!/usr/bin/env python3
import fcntl, hashlib, http.cookiejar, json, os, random, re, smtplib, subprocess, sys, time, traceback, urllib.parse, urllib.request
from email.message import EmailMessage

DB = "/var/lib/reseed/db.json"
TDIR = "/var/lib/reseed/torrents"
STATE = "/var/lib/reseed/watch.json"
LOG = "/var/log/reseed-watch.log"
RLOG = "/var/log/reseed-watch-runs.log"
QBIT = "http://localhost:8090"
PROWLARR = "http://localhost:9696"
QENV = "/etc/onepace-sync/qbit.env"
SMTP_ENV = "/etc/homeserver-tools/smtp.env"
EVERY = 6 * 3600
RECHECK_ZERO = 3600
SLOW = 7 * 86400
ERR_RETRY = 3600
BACKOFF = 2 * 3600
MAX_PER_RUN = 4
MAX_STARTS_DAY = 2
THRESH = 0
ZERO_HITS = 2
DRY = "--dry-run" in sys.argv
FORCE = "--force" in sys.argv


class Busy(Exception):
    pass


class Gone(Exception):
    pass


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def load(p, d):
    try:
        return json.load(open(p))
    except Exception:
        return d


def save(p, d):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, p)


def readenv(path):
    env = {}
    for l in open(path):
        l = l.strip()
        if not l or l.startswith("#") or "=" not in l:
            continue
        k, v = l.split("=", 1)
        env[k.removeprefix("export ").strip().upper()] = v.strip().strip("'\"")
    return env


def pick(env, *names, default=None, loose=False):
    for k, v in env.items():
        if set(re.split(r"[^A-Z0-9]+", k)) & set(names):
            return v
    if loose:
        for k, v in env.items():
            if any(n in k for n in names):
                return v
    return default


def mail(subj, body):
    try:
        env = readenv(SMTP_ENV)
        host = pick(env, "HOST", "SERVER", default="smtp.gmail.com")
        port = int(pick(env, "PORT", default="587"))
        user = pick(env, "USER", "USERNAME", "LOGIN", loose=True)
        pw = pick(env, "PASS", "PASSWORD", loose=True)
        to = pick(env, "TO", "RCPT", "RECIPIENT", default="you@example.com")
        m = EmailMessage()
        m["Subject"] = "[reseed-watch] " + subj
        m["From"] = pick(env, "FROM", "SENDER", default=user)
        m["To"] = to
        m.set_content(body)
        if port == 465:
            s = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            s = smtplib.SMTP(host, port, timeout=30)
            s.starttls()
        s.login(user, pw)
        s.send_message(m)
        s.quit()
    except Exception as ex:
        log(f"mail failed: {ex}")


def bdecode(b, i=0):
    c = b[i:i + 1]
    if c == b"i":
        j = b.index(b"e", i)
        return int(b[i + 1:j]), j + 1
    if c in (b"l", b"d"):
        i += 1
        out = [] if c == b"l" else {}
        while b[i:i + 1] != b"e":
            if c == b"l":
                v, i = bdecode(b, i)
                out.append(v)
            else:
                k, i = bdecode(b, i)
                v, i = bdecode(b, i)
                out[k] = v
        return out, i + 1
    j = b.index(b":", i)
    n = int(b[i:j])
    return b[j + 1:j + 1 + n], j + 1 + n


def infohash(raw):
    if raw[:1] != b"d":
        return None
    i = 1
    while raw[i:i + 1] != b"e":
        k, i = bdecode(raw, i)
        s = i
        _, i = bdecode(raw, i)
        if k == b"info":
            return hashlib.sha1(raw[s:i]).hexdigest()
    return None


def meta(h):
    m, _ = bdecode(open(f"{TDIR}/{h}.torrent", "rb").read())
    info = m[b"info"]
    if b"files" in info:
        size = sum(f[b"length"] for f in info[b"files"])
        size_np = sum(f[b"length"] for f in info[b"files"] if b"p" not in f.get(b"attr", b""))
    else:
        size = size_np = info[b"length"]
    ann = m.get(b"announce", b"").decode("utf-8", "replace")
    if not ann and m.get(b"announce-list"):
        ann = m[b"announce-list"][0][0].decode("utf-8", "replace")
    return {"name": info[b"name"].decode("utf-8", "replace"), "size": size, "size_np": size_np,
            "comment": m.get(b"comment", b"").decode("utf-8", "replace"),
            "host": urllib.parse.urlparse(ann).hostname or ""}


def reg(host):
    return ".".join((host or "").lower().split(":")[0].split(".")[-2:])


def qbit():
    env = readenv(QENV)
    u = pick(env, "USER", "USERNAME", loose=True)
    p = pick(env, "PASS", "PASSWORD", loose=True)
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op.open(urllib.request.Request(QBIT + "/api/v2/auth/login", data=urllib.parse.urlencode({"username": u, "password": p}).encode(), headers={"Referer": QBIT}), timeout=15)
    return op


def qinfo(op, h=None):
    return json.load(op.open(QBIT + "/api/v2/torrents/info" + (f"?hashes={h}" if h else ""), timeout=30))


def pkey():
    xml = subprocess.run(["docker", "exec", "prowlarr", "cat", "/config/config.xml"], capture_output=True, text=True).stdout
    return re.search(r"<ApiKey>(.*?)</ApiKey>", xml).group(1)


def pget(path, key, timeout=120):
    return json.load(urllib.request.urlopen(urllib.request.Request(PROWLARR + path, headers={"X-Api-Key": key}), timeout=timeout))


def apikey(i):
    for f in i.get("fields", []):
        if f.get("name", "").lower() in ("apikey", "api_key", "apitoken") and f.get("value"):
            return f["value"]


def indexers_for(ix, dom):
    return [i for i in ix if i.get("enable") and i.get("protocol") == "torrent" and dom in json.dumps(i).lower()]


def unit3d(host, tid, key):
    u = f"https://{host}/api/torrents/{tid}?api_token={urllib.parse.quote(key)}"
    r = subprocess.run(["docker", "exec", "prowlarr", "curl", "-s", "-m", "30", "-A", "reseed-watch", "-w", "\n%{http_code}", u], capture_output=True, text=True, timeout=60)
    body, _, code = r.stdout.rpartition("\n")
    if code == "429":
        raise Busy()
    if code == "404":
        raise Gone()
    if code != "200":
        raise RuntimeError(f"http {code}")
    j = json.loads(body)
    a = j.get("attributes") or j.get("data", {}).get("attributes", {})
    return a.get("seeders"), a.get("leechers")


def search(key, iid, q):
    return pget("/api/v1/search?" + urllib.parse.urlencode({"query": q, "indexerIds": iid, "type": "search", "limit": 100}), key)


def queries(name):
    q1 = re.sub(r"[._]+", " ", re.sub(r"\.(mkv|mp4|avi|m2ts|ts|iso)$", "", name, flags=re.I)).strip()
    out = [q1]
    m = re.match(r"(.+?\b(?:19|20)\d\d)\b", q1)
    if m and m.group(1) != q1:
        out.append(m.group(1))
    return out


def resolve(h, mt, key, iid):
    tol = max(2 << 20, mt["size"] * 0.002)
    diff = lambda r: min(abs(r["size"] - mt["size"]), abs(r["size"] - mt["size_np"]))
    for q in queries(mt["name"]):
        c = sorted([r for r in search(key, iid, q) if r.get("size") and diff(r) <= tol], key=diff)
        checked = 0
        for r in c[:5]:
            u = r.get("downloadUrl") or ""
            if not u.startswith("http"):
                continue
            pu = urllib.parse.urlparse(u)
            if pu.path.endswith("/download"):
                u = PROWLARR + pu.path + "?" + pu.query
            try:
                raw = urllib.request.urlopen(u, timeout=60).read()
                checked += 1
                if infohash(raw) == h:
                    return r, q, "infohash"
            except Exception as ex:
                log(f"  candidate download failed: {ex}")
            time.sleep(3)
        if not checked and len(c) == 1:
            return c[0], q, "size"
        time.sleep(3)
    return None, None, None


def search_seeders(m, key):
    for r in search(key, m["iid"], m["q"]):
        if (m.get("info") and r.get("infoUrl") == m["info"]) or (m.get("guid") and r.get("guid") == m["guid"]):
            return r.get("seeders"), r.get("leechers")
    return None, None


def check(h, w, mt, dom, ix, key):
    now = time.time()
    m = w.get("m")
    if not m:
        cm = re.search(r"https?://([^/\s]+)/torrents/(\d+)", mt["comment"])
        if cm and reg(cm.group(1)) == dom and any(apikey(i) for i in indexers_for(ix, dom)):
            m = w["m"] = {"via": "unit3d", "host": cm.group(1), "tid": cm.group(2)}
        else:
            idx = indexers_for(ix, dom)
            if not idx:
                w["note"] = "no Prowlarr indexer"
                w["next"] = now + SLOW
                return None
            r, q, how = resolve(h, mt, key, idx[0]["id"])
            if not r:
                w["note"] = "no match on tracker"
                w["next"] = now + SLOW
                return None
            w["m"] = {"via": "search", "iid": idx[0]["id"], "q": q, "info": r.get("infoUrl"), "guid": r.get("guid")}
            w["note"] = f"matched by {how}"
            return r.get("seeders"), r.get("leechers")
    if m["via"] == "unit3d":
        k = next((apikey(i) for i in indexers_for(ix, dom) if apikey(i)), None)
        if not k:
            raise RuntimeError("api key missing in Prowlarr")
        return unit3d(m["host"], m["tid"], k)
    return search_seeders(m, key)


def alive(pid):
    try:
        return "reseed" in open(f"/proc/{pid}/cmdline").read()
    except OSError:
        return False


def spawn(h):
    lf = open(RLOG, "a")
    lf.write(time.strftime("\n=== %Y-%m-%d %H:%M:%S ") + f"reseed {h} ===\n")
    lf.flush()
    return subprocess.Popen(["/usr/local/bin/reseed", h], stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True).pid


def tail():
    try:
        return "".join(open(RLOG).readlines()[-30:])
    except OSError:
        return ""


def status(st, db):
    now = time.time()
    print(f"{'torrent':<52}{'tracker':<18}{'via':<8}{'seed':>5}{'leech':>6}{'checked':>9}{'next':>7}  note")
    for h, w in sorted(st["t"].items(), key=lambda x: x[1].get("name", "")):
        if db["t"].get(h, {}).get("status") != "restorable":
            continue
        s, l = w.get("seeders"), w.get("leechers")
        chk = f"{(now - w['checked']) / 3600:.1f}h" if w.get("checked") else "-"
        nxt = f"{max(0, w.get('next', 0) - now) / 3600:.1f}h"
        via = (w.get("m") or {}).get("via", "-")
        print(f"{w.get('name', h)[:50]:<52}{w.get('tracker', ''):<18}{via:<8}{'-' if s is None else s:>5}{'-' if l is None else l:>6}{chk:>9}{nxt:>7}  {w.get('note') or ''}")
    r = st.get("running")
    print(f"\nrunning: {r['name'] if r else 'none'} | reseeds started last 24h: {sum(1 for t in st['starts'] if t > now - 86400)}/{MAX_STARTS_DAY}")


def main():
    if "--test-mail" in sys.argv:
        mail("test", "reseed-watch mail works.")
        return
    st = load(STATE, {})
    for k, d in (("t", {}), ("starts", []), ("running", None), ("backoff", {})):
        st.setdefault(k, d)
    db = load(DB, None)
    if not db:
        log("db unreadable, skipping run")
        return
    if "--status" in sys.argv:
        status(st, db)
        return
    lk = open("/run/reseed-watch.lock", "w")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    now = time.time()
    st["starts"] = [t for t in st["starts"] if t > now - 86400]
    op = qbit()
    inq = {t["hash"].lower() for t in qinfo(op)}
    r = st.get("running")
    if r and not alive(r["pid"]):
        t = qinfo(op, r["hash"])
        if t and t[0].get("progress", 0) >= 1:
            mail(f"reseeded: {r['name']}", f"{r['name']}\n{r['tracker']}\nSeeding again (category reseed).\n\n{tail()}")
            log(f"reseed done: {r['name']}")
        else:
            mail(f"RESEED FAILED: {r['name']}", f"{r['name']}\n{r['tracker']}\nNot complete. Either not added, or left stopped in qBittorrent.\n\n{tail()}")
            log(f"reseed FAILED: {r['name']}")
        st["running"] = None
    busy = bool(st["running"])
    key = pkey()
    ix = pget("/api/v1/indexer", key)
    due = []
    for h, e in db["t"].items():
        if e.get("status") != "restorable" or not os.path.exists(f"{TDIR}/{h}.torrent"):
            continue
        w = st["t"].setdefault(h, {})
        if h in inq:
            w["note"] = "seeding"
            w.setdefault("name", meta(h)["name"])
            continue
        if w.get("note") == "seeding":
            w["note"] = ""
        if FORCE or w.get("next", 0) <= now:
            due.append((h, e, w))
    random.shuffle(due)
    done, used = 0, set()
    for h, e, w in due:
        if not FORCE and done >= MAX_PER_RUN:
            break
        try:
            mt = meta(h)
        except Exception as ex:
            log(f"{h}: bad .torrent: {ex}")
            continue
        dom = reg(e.get("tracker") or mt["host"])
        w["name"], w["tracker"] = mt["name"], dom
        if st["backoff"].get(dom, 0) > now or (not FORCE and dom in used):
            continue
        used.add(dom)
        done += 1
        try:
            res = check(h, w, mt, dom, ix, key)
        except Busy:
            st["backoff"][dom] = now + BACKOFF
            log(f"{dom}: rate limited, backing off 2h")
            continue
        except Gone:
            w["note"] = "deleted on tracker"
            w["next"] = now + SLOW
            log(f"{mt['name'][:60]} [{dom}]: deleted on tracker")
            continue
        except Exception as ex:
            w["note"] = f"error: {str(ex)[:60]}"
            w["next"] = now + ERR_RETRY
            log(f"{mt['name'][:60]} [{dom}]: error {ex}")
            continue
        finally:
            if FORCE:
                time.sleep(5)
        if res is None:
            log(f"{mt['name'][:60]} [{dom}]: {w.get('note')}")
            continue
        s, l = res
        w["checked"], w["seeders"], w["leechers"] = now, s, l
        if s is None:
            w["note"] = "not in search results"
            w["next"] = now + EVERY
            log(f"{mt['name'][:60]} [{dom}]: not in search results")
            continue
        if s > THRESH:
            w["zero"] = 0
            w["next"] = now + EVERY + random.uniform(-1800, 1800)
            if (w.get("note") or "").startswith(("error", "not in", "dead")):
                w["note"] = ""
            log(f"{mt['name'][:60]} [{dom}]: {s} seeders, {l} leechers")
            continue
        w["zero"] = w.get("zero", 0) + 1
        log(f"{mt['name'][:60]} [{dom}]: 0 seeders ({w['zero']}/{ZERO_HITS})")
        if w["zero"] < ZERO_HITS:
            w["next"] = now + RECHECK_ZERO
            continue
        if DRY:
            log("  dry run: would reseed now")
            w["next"] = now + RECHECK_ZERO
            continue
        if busy or len(st["starts"]) >= MAX_STARTS_DAY:
            w["note"] = "dead, queued"
            w["next"] = now + RECHECK_ZERO
            continue
        pid = spawn(h)
        st["running"] = {"hash": h, "pid": pid, "name": mt["name"], "tracker": dom, "start": now}
        st["starts"].append(now)
        busy = True
        w["zero"], w["note"], w["next"] = 0, "reseeded", now + EVERY
        log(f"  reseed started, pid {pid}")
        mail(f"dead torrent, reseeding: {mt['name']}", f"{mt['name']}\n{dom}\n0 seeders on {ZERO_HITS} checks an hour apart.\nreseed started (pid {pid}), log: {RLOG}\nAnother mail follows when it's seeding or if it fails.")
    save(STATE, st)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("crash:\n" + traceback.format_exc())
