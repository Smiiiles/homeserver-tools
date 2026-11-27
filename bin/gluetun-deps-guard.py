#!/usr/bin/env python3
import json,subprocess,datetime,sys,os
LOG="/var/log/gluetun-deps-guard.log"
GRACE=60
NOTE=[]
def log(m,mail=True):
    if mail: NOTE.append(m)
    with open(LOG,"a") as f:
        f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S ")+m+"\n")
def sh(*a):
    return subprocess.run(a,capture_output=True,text=True)
if os.environ.get("MAILTEST")=="1":
    NOTE.append("test mail from gluetun-deps-guard")
def started(c):
    return datetime.datetime.fromisoformat(c["State"]["StartedAt"][:19]+"+00:00")
r=sh("docker","inspect","gluetun")
if r.returncode:
    sys.exit(0)
g=json.loads(r.stdout)[0]
if not g["State"]["Running"] or g["State"].get("Health",{}).get("Status")!="healthy":
    sys.exit(0)
gs=started(g)
dry=os.environ.get("DRYRUN")=="1"
if dry:
    gs=datetime.datetime.now(datetime.timezone.utc)
elif (datetime.datetime.now(datetime.timezone.utc)-gs).total_seconds()<GRACE:
    sys.exit(0)
ids=sh("docker","ps","-q").stdout.split()
if not ids:
    sys.exit(0)
names={g["Id"],g["Name"].lstrip("/"),"gluetun"}
stale={}
for c in json.loads(sh("docker","inspect",*ids).stdout):
    nm=c["HostConfig"]["NetworkMode"]
    if not nm.startswith("container:"):
        continue
    lab=c["Config"]["Labels"] or {}
    target=nm.split(":",1)[1]
    current=target in names
    if not current and "gluetun" not in lab.get("com.docker.compose.depends_on",""):
        continue
    if current and started(c)>=gs:
        continue
    key=(lab.get("com.docker.compose.project",""),lab.get("com.docker.compose.project.config_files",""),lab.get("com.docker.compose.project.working_dir",""))
    stale.setdefault(key,[]).append(lab.get("com.docker.compose.service",c["Name"].lstrip("/")))
for (proj,files,wd),svcs in stale.items():
    if not files:
        log("SKIPPED no compose labels: "+" ".join(svcs))
        continue
    cmd=["docker","compose","-p",proj,"--project-directory",wd]
    for f in files.split(","):
        cmd+=["-f",f]
    cmd+=["up","-d","--force-recreate","--no-deps",*svcs]
    if dry:
        print(" ".join(cmd))
        continue
    r=sh(*cmd)
    if r.returncode==0:
        log("recreated "+" ".join(svcs)+" (gluetun started "+g["State"]["StartedAt"][:19]+"Z)",False)
    else:
        log("FAILED "+" ".join(svcs)+": "+r.stderr.strip()[-400:])
if NOTE:
    import smtplib
    from email.message import EmailMessage
    e=dict(l.strip().split("=",1) for l in open("/etc/homeserver-tools/smtp.env") if "=" in l)
    e={k:v.strip("\"'") for k,v in e.items()}
    m=EmailMessage()
    m["Subject"]="HomeServer: gluetun-deps-guard acted"
    m["From"]=e["SMTP_USER"]
    m["To"]=e["MAIL_TO"]
    m.set_content("\n".join(NOTE))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com",465,timeout=30) as srv:
            srv.login(e["SMTP_USER"],e["SMTP_PASS"])
            srv.send_message(m)
    except Exception as x:
        with open(LOG,"a") as f:
            f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S ")+"mail failed: "+str(x)+"\n")
