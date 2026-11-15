"""Lecture seule (+ 3 petits appels Apify/Gemini) : pourquoi les stories donnent-elles si peu d'events ?"""
import json, os, sys, collections
sys.path.insert(0, os.getcwd())
from config import settings
from src import airtable_client as at, apify_client, gemini_client, publication_supabase as ps

# 1) echantillon de lignes sans legende (stories) : ce que Gemini en a tire
rows = at.search_records(settings.AIRTABLE_TABLE_EVENTS,
    formula=f"AND(LEN({{{settings.FLD_LEGENDE}}}) = 0, IS_AFTER(CREATED_TIME(), DATETIME_PARSE('2026-10-12')), IS_BEFORE(CREATED_TIME(), DATETIME_PARSE('2026-11-10')))",
    max_records=200)
alerts = collections.Counter()
for r in rows:
    f = r["fields"]
    a = (f.get(settings.FLD_ALERTE) or "")[:110]
    alerts[a] += 1
print(f"::notice::lignes sans legende={len(rows)}; titres vides={sum(1 for r in rows if not r['fields'].get(settings.FLD_TITRE))}; dates vides={sum(1 for r in rows if not r['fields'].get(settings.FLD_DATE))}")
for a, n in alerts.most_common(8):
    print(f"::notice::alerte x{n} | {a}")
for r in rows[:8]:
    f = r["fields"]
    print(f"::notice::ex | {f.get(settings.FLD_VENUE_NAME)} | titre={f.get(settings.FLD_TITRE)!r} | date={f.get(settings.FLD_DATE)} | statut={f.get(settings.FLD_STATUT)}")

# 2) test en direct sur 4 venues scrapees tous les jours
venues = ps._request("GET", "venues", params={"select": "name,instagram_url,scrape_frequency,client_type", "scrape_frequency": "eq.everyday", "client_type": "eq.not_a_client", "limit": "400"}) or []
import random; random.seed(7)
for v in random.sample(venues, 6):
    user = v["instagram_url"].rstrip("/").split("/")[-1]
    stories = apify_client.scrape_stories(user)
    print(f"::notice::stories | {v['name']} (@{user}) | recues={len(stories)}")
    for s in stories[:2]:
        cands = [c.get("url") for c in (s.get("image_versions2") or {}).get("candidates", []) if c.get("url")]
        keys = list(s.keys())[:12]
        print(f"::notice::  story keys={keys} images={len(cands)} video={'video_versions' in s}")
        if cands:
            try:
                res = gemini_client.extract_from_images(cands[:1], published_timestamp="")
                print(f"::notice::  gemini -> {json.dumps(res, ensure_ascii=False)[:300]}")
            except Exception as exc:
                print(f"::notice::  gemini ERREUR {type(exc).__name__}: {str(exc)[:200]}")
