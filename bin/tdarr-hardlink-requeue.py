#!/usr/bin/env python3
import json, os, urllib.request, datetime
L = "/home/htpc/docker/tdarr/server/hardlink_skipped.txt"
stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
if not os.path.exists(L):
    print(stamp, "no skip list yet")
    raise SystemExit(0)
paths = sorted(set(l.strip() for l in open(L) if l.strip()))
keep, requeued, gone = [], 0, 0
for p in paths:
    host = "/mnt" + p
    if not os.path.exists(host):
        gone += 1
        continue
    if os.stat(host).st_nlink > 1:
        keep.append(p)
        continue
    body = json.dumps({"data": {"collection": "FileJSONDB", "mode": "update", "docID": p, "obj": {"TranscodeDecisionMaker": "Queued"}}}).encode()
    req = urllib.request.Request("http://127.0.0.1:8265/api/v2/cruddb", data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).read()
    requeued += 1
tmp = L + ".tmp"
open(tmp, "w").write("".join(k + "\n" for k in keep))
os.chown(tmp, 1001, 1001)
os.replace(tmp, L)
print(stamp, f"requeued {requeued}, still linked {len(keep)}, gone {gone}")
