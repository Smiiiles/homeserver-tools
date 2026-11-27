import json, urllib.request
apps = {"Sonarr": ("http://localhost:8989", "CHANGE_ME_API_KEY"), "Radarr": ("http://localhost:7878", "CHANGE_ME_API_KEY")}
for app, (base, key) in apps.items():
    h = {"X-Api-Key": key, "Content-Type": "application/json"}
    idxs = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/api/v3/indexer", headers=h)).read())
    for i in idxs:
        f = next((x for x in i["fields"] if x["name"] == "failDownloads"), None)
        if f is None:
            print(f"{app} | {i['name']}: no failDownloads field")
            continue
        if sorted(f.get("value") or []) == [0, 1]:
            print(f"{app} | {i['name']}: already set")
            continue
        f["value"] = [0, 1]
        req = urllib.request.Request(f"{base}/api/v3/indexer/{i['id']}?forceSave=true", data=json.dumps(i).encode(), headers=h, method="PUT")
        urllib.request.urlopen(req).read()
        print(f"{app} | {i['name']}: set Executables + Potentially Dangerous")
