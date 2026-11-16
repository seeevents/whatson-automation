"""Lecture seule : schedules Apify et runs du 13-14 nov (qui a visite app.see.events ?)."""
import os, json, requests
T = os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_API_TOKEN")
H = {"Authorization": f"Bearer {T}"}
B = "https://api.apify.com/v2"
def get(p, **q):
    r = requests.get(B + p, headers=H, params=q, timeout=60); r.raise_for_status(); return r.json()["data"]
sch = get("/schedules", limit=100)
print(f"::notice::schedules={len(sch.get('items', []))}")
for s in sch.get("items", []):
    print(f"::notice::SCHEDULE {s.get('name')} enabled={s.get('isEnabled')} cron={s.get('cronExpression')} actions={[a.get('actorId') or a.get('actorTaskId') for a in s.get('actions', [])]}")
tasks = get("/actor-tasks", limit=100)
for t in tasks.get("items", []):
    print(f"::notice::TASK {t.get('name')} id={t.get('id')} actId={t.get('actId')} modified={t.get('modifiedAt')}")
runs = get("/actor-runs", limit=1000, desc=1)
import collections
c = collections.Counter(); first = {}
for r in runs["items"]:
    st = r.get("startedAt", "")
    if "2026-11-13T18" <= st[:13] <= "2026-11-14T06":
        k = (r.get("actId"), r.get("meta", {}).get("origin"))
        c[k] += 1; first.setdefault(k, st)
for k, n in c.most_common(15):
    print(f"::notice::RUNS 13-14nov actId={k[0]} origin={k[1]} n={n} premier={first[k]}")
