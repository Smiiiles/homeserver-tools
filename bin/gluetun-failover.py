#!/usr/bin/env python3
import fcntl, json, os, smtplib, subprocess, sys, time, urllib.request
from email.message import EmailMessage

ENV = "/home/htpc/docker/gluetun/gluetun.env"
COMPOSE = "/home/htpc/docker/docker-compose.yml"
STATE = "/var/lib/gluetun-failover/state.json"
LOG = "/var/log/gluetun-failover.log"
LOCK = "/run/gluetun-failover.lock"
SMTP_ENV = "/etc/homeserver-tools/smtp.env"
COUNTRY = "se"
POOL = ("Formosa", "Segin")
FAIL_CHECKS = 5
LOAD_MAX = 95
LOAD_CHECKS = 30
GRACE_MIN = 10
MAX_SWITCHES = 4
SWITCH_WINDOW_H = 6


def log(m):
    with open(LOG, "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")


def load_state():
    try:
        with open(STATE) as f:
            s = json.load(f)
    except Exception:
        s = {}
    for k, v in {"fails": 0, "hot": 0, "last_switch": 0, "switches": [], "capped": False, "no_target": False}.items():
        s.setdefault(k, v)
    return s


def save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(s, f)


def smtp_conf():
    d = {}
    with open(SMTP_ENV) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip().upper()] = v.strip().strip('"').strip("'")

    def pick(*keys, default=None):
        for k in keys:
            if d.get(k):
                return d[k]
        return default

    user = pick("SMTP_USER", "SMTP_USERNAME", "GMAIL_USER", "MAIL_USER", "USER", "USERNAME", "SMTP_FROM", "MAIL_FROM", "FROM")
    return {
        "host": pick("SMTP_HOST", "SMTP_SERVER", "HOST", "SERVER", default="smtp.gmail.com"),
        "port": int(pick("SMTP_PORT", "PORT", default="587")),
        "user": user,
        "pass": pick("SMTP_PASS", "SMTP_PASSWORD", "GMAIL_APP_PASSWORD", "APP_PASSWORD", "MAIL_PASS", "MAIL_PASSWORD", "PASSWORD", "PASS"),
        "from": pick("SMTP_FROM", "MAIL_FROM", "FROM", default=user),
        "to": pick("MAIL_TO", "SMTP_TO", "TO", "RECIPIENT", default="you@example.com"),
    }


def mail(subject, body):
    try:
        c = smtp_conf()
        m = EmailMessage()
        m["Subject"] = subject
        m["From"] = c["from"]
        m["To"] = c["to"]
        m.set_content(body)
        with smtplib.SMTP(c["host"], c["port"], timeout=30) as s:
            s.starttls()
            s.login(c["user"], c["pass"])
            s.send_message(m)
        log("mail sent: " + subject)
    except Exception as e:
        log(f"mail failed: {e}")


def sh(*a, timeout=60):
    return subprocess.run(a, capture_output=True, text=True, timeout=timeout)


def health():
    try:
        return sh("docker", "inspect", "gluetun", "--format", "{{.State.Health.Status}}").stdout.strip() or "missing"
    except Exception:
        return "error"


def whoami():
    try:
        r = sh("docker", "exec", "gluetun", "wget", "-qO-", "-T", "10", "https://airvpn.org/api/whatismyip/", timeout=25)
        j = json.loads(r.stdout)
        if j.get("airvpn"):
            return j.get("ip"), j.get("server_name")
    except Exception:
        pass
    return None, None


def servers():
    try:
        with urllib.request.urlopen("https://airvpn.org/api/status/", timeout=20) as r:
            data = json.load(r)
        return [s for s in data["servers"] if s.get("country_code", "").lower() == COUNTRY]
    except Exception as e:
        log(f"AirVPN status API failed: {e}")
        return []


def pinned():
    with open(ENV) as f:
        for line in f:
            if line.startswith("SERVER_NAMES="):
                return line.split("=", 1)[1].strip()
    return None


def set_pinned(name):
    with open(ENV) as f:
        lines = f.read().splitlines()
    out = [f"SERVER_NAMES={name}" if l.startswith("SERVER_NAMES=") else l for l in lines]
    with open(ENV, "w") as f:
        f.write("\n".join(out) + "\n")


def recreate():
    ids = sh("docker", "ps", "-aq").stdout.split()
    deps = []
    if ids:
        r = sh("docker", "inspect", "--format", '{{index .Config.Labels "com.docker.compose.service"}} {{.HostConfig.NetworkMode}}', *ids)
        for l in r.stdout.splitlines():
            p = l.split()
            if len(p) == 2 and p[1].startswith("container:") and p[0]:
                deps.append(p[0])
    r = sh("docker", "compose", "-f", COMPOSE, "up", "-d", "--force-recreate", "gluetun", *deps, timeout=300)
    log(f"recreated gluetun {' '.join(deps)} rc={r.returncode}")
    return r.returncode == 0


def pick_target(exclude):
    c = [s for s in servers() if s.get("health") == "ok" and s.get("public_name") in POOL and s.get("public_name") not in exclude]
    c.sort(key=lambda s: (0 if s.get("bw_max", 0) >= 10000 else 1, s.get("currentload", 999)))
    return c[0] if c else None


def switch(st, cur, reason):
    now = time.time()
    st["switches"] = [t for t in st["switches"] if now - t < SWITCH_WINDOW_H * 3600]
    if len(st["switches"]) >= MAX_SWITCHES:
        log(f"switch limit reached ({MAX_SWITCHES} in {SWITCH_WINDOW_H}h), staying on {cur}")
        if not st["capped"]:
            mail("gluetun-failover: switch limit hit", f"{reason}\n\nAlready switched {MAX_SWITCHES} times in {SWITCH_WINDOW_H}h, so not switching again. Staying on {cur}. Check gluetun and AirVPN manually.")
            st["capped"] = True
        return
    t = pick_target({cur})
    if not t:
        log("no healthy target server")
        if not st["no_target"]:
            mail("gluetun-failover: no healthy server", f"{reason}\n\nNo other healthy Swedish AirVPN server found. Staying on {cur}.")
            st["no_target"] = True
        return
    name = t["public_name"]
    log(f"switching {cur} -> {name} (load {t.get('currentload')}%, {t.get('bw_max')} Mbit): {reason}")
    set_pinned(name)
    ok = recreate()
    st.update(fails=0, hot=0, last_switch=now, capped=False, no_target=False)
    st["switches"].append(now)
    ip, srv = whoami()
    mail(f"gluetun-failover: switched to {name}", f"{reason}\n\nSwitched {cur} -> {name}.\nRecreate ok: {ok}\nNew exit: {ip} ({srv})\n\nNew IP means trackers mark you unconnectable for up to 30-60 min.")


CF_HOST = "cloudflare.com"
CF_EVERY_MIN = 60


def cf_check(st, ip):
    now = time.time()
    if now - st.get("cf_last", 0) < CF_EVERY_MIN * 60:
        return
    st["cf_last"] = now
    cf = None
    try:
        r = sh("docker", "exec", "gluetun", "wget", "-qO-", "-T", "10", f"https://{CF_HOST}/cdn-cgi/trace", timeout=25)
        cf = next((l.split("=", 1)[1].strip() for l in r.stdout.splitlines() if l.startswith("ip=")), None)
    except Exception:
        pass
    if not cf or not ip:
        log(f"cloudflare check: could not read IPs (general={ip}, cloudflare={cf})")
        return
    if cf != ip:
        log(f"cloudflare check: MISMATCH general={ip} cloudflare={cf}")
        if not st.get("cf_alerted"):
            mail("gluetun-failover: Cloudflare sees a different exit IP", f"Cloudflare-hosted sites ({CF_HOST}) see your VPN exit as {cf}, but gluetun's general exit is {ip}.\n\nYour forwarded port only works on {ip}, so trackers behind Cloudflare will mark you unconnectable.\n\nMost likely cause: AirVPN's anti-geolocation routing is active again. Check AirVPN Client Area > DNS > 'AirVPN anti-geolocation system' is 'Not active / neutral'.")
            st["cf_alerted"] = True
    else:
        log(f"cloudflare check: ok ({ip})")
        if st.get("cf_alerted"):
            mail("gluetun-failover: Cloudflare exit IP matches again", f"Cloudflare-hosted sites see {ip} again, same as gluetun's general exit. Trackers should show you connectable after their next check.")
            st["cf_alerted"] = False


def main():
    if "--test-mail" in sys.argv:
        mail("gluetun-failover test", "Test mail from gluetun-failover on HomeServer.")
        return
    if "--cf-check" in sys.argv:
        st = load_state()
        st["cf_last"] = 0
        ip, _ = whoami()
        cf_check(st, ip)
        save_state(st)
        return
    if "--status" in sys.argv:
        print("pinned:", pinned())
        print(json.dumps(load_state(), indent=1))
        return
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    st = load_state()
    now = time.time()
    cur = pinned()
    h = health()
    ip, srv = whoami() if h == "healthy" else (None, None)
    if cur and "," in cur and srv:
        set_pinned(srv)
        log(f"pinned SERVER_NAMES to current server {srv} ({ip}), applies on next recreate")
        cur = srv
    if now - st["last_switch"] < GRACE_MIN * 60:
        save_state(st)
        return
    if h != "healthy" or not ip:
        st["fails"] += 1
        log(f"gluetun not ok on {cur} (health={h}, ip={ip}), check {st['fails']}/{FAIL_CHECKS}")
        if st["fails"] >= FAIL_CHECKS:
            switch(st, cur, f"gluetun down for {st['fails']} checks on {cur}")
        save_state(st)
        return
    if st["fails"]:
        log(f"gluetun recovered on {srv} ({ip}) after {st['fails']} failed checks")
        if st["fails"] >= 3:
            mail("gluetun-failover: VPN recovered", f"gluetun was down for {st['fails']} checks and recovered on {srv} ({ip}) without switching.")
    cf_check(st, ip)
    st["fails"] = 0
    load = next((s.get("currentload") for s in servers() if s.get("public_name") == srv), None)
    st["hot"] = st["hot"] + 1 if load is not None and load >= LOAD_MAX else 0
    if st["hot"] >= LOAD_CHECKS:
        switch(st, srv, f"{srv} at {load}% load for {st['hot']} checks")
    save_state(st)


if __name__ == "__main__":
    main()
