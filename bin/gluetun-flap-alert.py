#!/usr/bin/env python3
import json, os, smtplib, subprocess, sys, time
from email.message import EmailMessage
STATE = "/var/lib/gluetun-flap-alert/state.json"
LOG = "/var/log/gluetun-flap-alert.log"
LIMIT = 5
def log(m):
    with open(LOG, "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M ") + m + "\n")
def smtp_cfg():
    c = {"host": "smtp.gmail.com", "port": 587, "user": "you@example.com", "pass": None, "to": "you@example.com"}
    for l in open("/etc/homeserver-tools/smtp.env"):
        l = l.strip()
        if "=" not in l or l.startswith("#"):
            continue
        k, v = l.split("=", 1)
        k = k.replace("export ", "").strip().upper()
        v = v.strip().strip("\"'")
        if "HOST" in k or "SERVER" in k:
            c["host"] = v
        elif "PORT" in k:
            c["port"] = int(v)
        elif "PASS" in k:
            c["pass"] = v
        elif "USER" in k or "LOGIN" in k:
            c["user"] = v
        elif k.endswith("TO") or "RECIPIENT" in k:
            c["to"] = v
    return c
def mail(subject, body):
    c = smtp_cfg()
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = c["user"], c["to"], subject
    m.set_content(body)
    if c["port"] == 465:
        s = smtplib.SMTP_SSL(c["host"], c["port"], timeout=30)
    else:
        s = smtplib.SMTP(c["host"], c["port"], timeout=30)
        s.starttls()
    s.login(c["user"], c["pass"])
    s.send_message(m)
    s.quit()
if "--test-mail" in sys.argv:
    mail("HomeServer: gluetun-flap-alert test", "Test mail from gluetun-flap-alert on HomeServer.")
    print("test mail sent")
    sys.exit(0)
os.makedirs(os.path.dirname(STATE), exist_ok=True)
try:
    st = json.load(open(STATE))
except Exception:
    st = {"alerting": False, "last": 0}
now = time.time()
running = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "gluetun"], capture_output=True, text=True).stdout.strip()
out = subprocess.run(["docker", "logs", "--since", "10m", "gluetun"], capture_output=True, text=True)
lines = (out.stdout + out.stderr).splitlines()
restarts = [l for l in lines if "restarting VPN" in l]
servers = sorted({l.rsplit(" ", 1)[-1] for l in lines if "Connecting to" in l})
bad = running != "true" or len(restarts) >= LIMIT
if bad and (not st["alerting"] or now - st["last"] > 3600):
    body = (f"gluetun running: {running}\nVPN restarts in the last 10 min: {len(restarts)}\n"
            f"Servers tried: {', '.join(servers) or 'none'}\n\nLast restarts:\n"
            + "\n".join(r[:300] for r in restarts[-3:])
            + "\n\nqBittorrent, Prowlarr, autobrr and FlareSolverr have no network while this lasts.")
    mail(f"HomeServer: gluetun VPN flapping ({len(restarts)} restarts in 10 min)", body)
    st.update(alerting=True, last=now)
    log(f"alert sent, restarts {len(restarts)}, running {running}")
elif not bad and st["alerting"] and not restarts:
    mail("HomeServer: gluetun VPN stable again", f"No VPN restarts in the last 10 min. gluetun running: {running}")
    st.update(alerting=False)
    log("recovery mail sent")
with open(STATE, "w") as f:
    json.dump(st, f)
