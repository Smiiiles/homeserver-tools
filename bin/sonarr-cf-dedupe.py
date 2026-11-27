#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import re
import traceback
import urllib.error
import urllib.request

APPS = [
    {"name": "sonarr", "url": "http://localhost:8989/api/v3", "key": "CHANGE_ME_API_KEY"},
    {"name": "radarr", "url": "http://localhost:7878/api/v3", "key": "CHANGE_ME_API_KEY"},
]
DEDUPE = "zz Dedupe - "
MIRROR = "zz Tdarr - "
TDARR_NAME = re.compile(r"\([^()]*\s-\s([^()]+?)\)\.[A-Za-z0-9]{2,4}$")
TDARR_TAIL = r"\)(?:\.[a-z0-9]{2,4})?$"
IGNORE_GROUPS = {"unknowngroup", "sonarr", "radarr"}
GROUP_IMPLS = ("ReleaseGroupSpecification", "ReleaseTitleSpecification")
SAFE_NAME = re.compile(r"^[\w.\- ]+$")
PLAIN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\- ]*$")


def api(app, method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        app["url"] + path,
        data=data,
        method=method,
        headers={"X-Api-Key": app["key"], "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode(errors='replace')[:2000]}") from None
    return json.loads(raw) if raw else None


def value_of(spec):
    for field in spec.get("fields", []):
        if field.get("name") == "value":
            return str(field.get("value") or "")
    return ""


def balanced(s):
    depth = 0
    for i, c in enumerate(s):
        escaped = i > 0 and s[i - 1] == "\\"
        if c == "(" and not escaped:
            depth += 1
        elif c == ")" and not escaped:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def raw_names(value):
    v = re.sub(r"^\(\?i\)", "", value.strip())
    v = v.replace(r"\b", "").lstrip("^").rstrip("$")
    while v.startswith("(") and v.endswith(")") and balanced(v[1:-1]):
        v = v[1:-1]
        if v.startswith("?:"):
            v = v[2:]
    if "(" in v or ")" in v:
        return []
    return [p.strip() for p in v.split("|") if p.strip()]


def group_keys(spec):
    keys = {spec["name"].strip().lower()}
    keys |= {n.lower() for n in raw_names(value_of(spec)) if SAFE_NAME.match(n)}
    return keys


def tdarr_frags(spec):
    frags = []
    name = spec["name"].strip()
    if SAFE_NAME.match(name):
        frags.append(re.escape(name))
    for n in raw_names(value_of(spec)):
        if PLAIN_NAME.match(n) and re.escape(n) not in frags:
            frags.append(re.escape(n))
    return frags


def tdarr_regex(spec):
    frags = tdarr_frags(spec)
    if not frags:
        return None
    return r"\s-\s(?:" + "|".join(frags) + ")" + TDARR_TAIL


def is_group_spec(spec):
    return (spec.get("implementation") in GROUP_IMPLS
            and not spec.get("negate") and not spec.get("required"))


def spec_key(spec):
    fields = sorted((f.get("name"), json.dumps(f.get("value"))) for f in spec.get("fields", []))
    return json.dumps([spec.get("implementation"), bool(spec.get("negate")),
                       bool(spec.get("required")), fields])


def clean_spec(spec, **over):
    s = {
        "name": spec["name"],
        "implementation": spec["implementation"],
        "negate": bool(spec.get("negate")),
        "required": bool(spec.get("required")),
        "fields": [{"name": f["name"], "value": f.get("value")} for f in spec.get("fields", [])],
    }
    s.update(over)
    return s


def title_spec(name, value, required=False, negate=False):
    return {"name": name, "implementation": "ReleaseTitleSpecification", "negate": negate,
            "required": required, "fields": [{"name": "value", "value": value}]}


def unique(specs):
    seen = {}
    for s in specs:
        seen.setdefault(spec_key(s), s)
    return list(seen.values())


def is_tier(cf):
    n = cf["name"].lower()
    return "tier" in n and not cf["name"].startswith("zz ") and not n.startswith("manual")


def is_anime(cf):
    return cf["name"].lower().startswith("anime")


def analyse(cf):
    groups = {}
    cons = []
    for spec in cf.get("specifications", []):
        if is_group_spec(spec):
            for k in group_keys(spec):
                groups.setdefault(k, spec)
        else:
            cons.append(spec)
    return groups, cons


def too_complex(cons):
    return any(s["implementation"] in GROUP_IMPLS and not s.get("required") for s in cons)


def merge_constraints(a, b):
    out = {}
    for s in a + b:
        if s.get("required"):
            out[spec_key(s)] = s

    def optional(lst):
        d = {}
        for s in lst:
            if not s.get("required"):
                d.setdefault(s["implementation"], {})[spec_key(s)] = s
        return d

    oa, ob = optional(a), optional(b)
    for impl in set(oa) | set(ob):
        if impl in oa and impl in ob:
            common = oa[impl].keys() & ob[impl].keys()
            if not common:
                return None
            for k in common:
                out[k] = oa[impl][k]
        else:
            out.update(oa.get(impl) or ob[impl])
    return list(out.values())


def group_match_spec(spec, label):
    if spec["implementation"] == "ReleaseTitleSpecification":
        v = value_of(spec)
        t = tdarr_regex(spec)
        if t:
            v = f"(?:{v})|{t}"
        return title_spec(label, v, required=True)
    return clean_spec(spec, name=label, required=True, negate=False)


def file_records(app):
    if app["name"] == "sonarr":
        for s in api(app, "GET", "/series"):
            yield from api(app, "GET", f"/episodefile?seriesId={s['id']}")
    else:
        for m in api(app, "GET", "/movie"):
            if m.get("movieFile"):
                yield m["movieFile"]


def fix_groups(app, dry):
    kind = "episodefile" if app["name"] == "sonarr" else "moviefile"
    changed = []
    for f in file_records(app):
        m = TDARR_NAME.search(os.path.basename(f.get("relativePath") or ""))
        if not m:
            continue
        group = m.group(1).strip()
        if group.lower() in IGNORE_GROUPS or f.get("releaseGroup") == group:
            continue
        print(f"[{app['name']}] group {f.get('releaseGroup')!r} -> {group!r}  {f['relativePath']}")
        f["releaseGroup"] = group
        changed.append(f)
    if changed and not dry:
        for i in range(0, len(changed), 100):
            api(app, "PUT", f"/{kind}/bulk", changed[i:i + 100])
    print(f"[{app['name']}] release groups fixed: {len(changed)}")


def build(app, extra, overrides):
    cfs = api(app, "GET", "/customformat")
    profiles = api(app, "GET", "/qualityprofile")
    by_id = {c["id"]: c for c in cfs}
    tiers = {c["id"]: analyse(c) for c in cfs if is_tier(c)}
    desired = {}

    for p in profiles:
        scores = {fi["format"]: fi["score"] for fi in p["formatItems"]}
        for a, (ga, ca) in tiers.items():
            if not is_anime(by_id[a]) or scores.get(a, 0) <= 0:
                continue
            for n, (gn, cn) in tiers.items():
                if is_anime(by_id[n]) or scores.get(n, 0) <= 0:
                    continue
                for g in sorted(ga.keys() & gn.keys()):
                    name = f"{DEDUPE}{g} [{by_id[a]['name']} x {by_id[n]['name']}]"
                    if name not in desired:
                        cons = merge_constraints(ca, cn)
                        if cons is None:
                            print(f"[{app['name']}] skip {name}: release types never overlap")
                            desired[name] = None
                            continue
                        if too_complex(cons):
                            print(f"[{app['name']}] skip {name}: conditions too complex to merge")
                            desired[name] = None
                            continue
                        specs = unique([group_match_spec(ga[g], f"{g} A"),
                                        group_match_spec(gn[g], f"{g} B")]
                                       + [clean_spec(s) for s in cons])
                        desired[name] = {"specs": specs, "scores": {}}
                    if desired[name] is None:
                        continue
                    target = -min(scores[a], scores[n]) - overrides.get(g, extra)
                    desired[name]["scores"][p["id"]] = target
                    print(f"[{app['name']}] overlap [{p['name']}] {g}: {by_id[a]['name']}={scores[a]} / "
                          f"{by_id[n]['name']}={scores[n]} -> {target}")

    for cid, (groups, cons) in tiers.items():
        title_groups = {spec_key(s): s for s in groups.values()
                        if s["implementation"] == "ReleaseTitleSpecification"}
        if not title_groups:
            continue
        name = f"{MIRROR}{by_id[cid]['name']}"
        if too_complex(cons):
            print(f"[{app['name']}] skip {name}: conditions too complex to mirror")
            continue
        frags = []
        negs = []
        for s in title_groups.values():
            for f in tdarr_frags(s):
                if f not in frags:
                    frags.append(f)
            negs.append(title_spec(f"Not {s['name']}", value_of(s), required=True, negate=True))
        if not frags:
            continue
        tdarr = [title_spec("Tdarr filename group", r"\s-\s(?:" + "|".join(frags) + ")" + TDARR_TAIL, required=True)]
        scores = {p["id"]: next((fi["score"] for fi in p["formatItems"] if fi["format"] == cid), 0)
                  for p in profiles}
        desired[name] = {"specs": unique([clean_spec(s) for s in cons] + tdarr + negs), "scores": scores}
        print(f"[{app['name']}] mirror {name}: {len(frags)} groups")

    return {k: v for k, v in desired.items() if v is not None}


def apply(app, desired, dry):
    cfs = api(app, "GET", "/customformat")
    existing = {c["name"]: c for c in cfs if c["name"].startswith((DEDUPE, MIRROR))}
    for name, d in desired.items():
        body = {"name": name, "includeCustomFormatWhenRenaming": False, "specifications": d["specs"]}
        old = existing.get(name)
        if old is None:
            print(f"[{app['name']}] create CF {name}")
            if not dry:
                try:
                    api(app, "POST", "/customformat", body)
                except Exception as e:
                    print(f"[{app['name']}] ERROR {name}: {e}")
        elif sorted(map(spec_key, old["specifications"])) != sorted(map(spec_key, d["specs"])):
            print(f"[{app['name']}] update CF {name}")
            if not dry:
                body["id"] = old["id"]
                try:
                    api(app, "PUT", f"/customformat/{old['id']}", body)
                except Exception as e:
                    print(f"[{app['name']}] ERROR {name}: {e}")
    for name, c in existing.items():
        if name not in desired:
            print(f"[{app['name']}] delete stale CF {name}")
            if not dry:
                api(app, "DELETE", f"/customformat/{c['id']}")
    if dry:
        return
    for p in api(app, "GET", "/qualityprofile"):
        dirty = False
        for fi in p["formatItems"]:
            if fi["name"] in desired:
                target = desired[fi["name"]]["scores"].get(p["id"], 0)
                if fi["score"] != target:
                    fi["score"] = target
                    dirty = True
        if dirty:
            print(f"[{app['name']}] scores updated in profile {p['name']}")
            api(app, "PUT", f"/qualityprofile/{p['id']}", p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--extra", type=int, default=0)
    ap.add_argument("--extra-group", action="append", default=[])
    args = ap.parse_args()
    overrides = {k.strip().lower(): int(v) for k, v in (x.split("=", 1) for x in args.extra_group)}
    print(f"=== {datetime.datetime.now().isoformat(timespec='seconds')} dry={args.dry_run} extra={args.extra}")
    for app in APPS:
        try:
            fix_groups(app, args.dry_run)
            apply(app, build(app, args.extra, overrides), args.dry_run)
        except Exception:
            print(f"[{app['name']}] FAILED")
            traceback.print_exc()


if __name__ == "__main__":
    main()
