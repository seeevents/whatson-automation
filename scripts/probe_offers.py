"""Lecture seule : structure de venue_offers (colonnes + 5 exemples)."""
import json, os, sys
sys.path.insert(0, os.getcwd())
from src import publication_supabase as ps
rows = ps._request("GET", "venue_offers", params={"select": "*", "limit": "5", "order": "created_at.desc"}) or []
print(f"::notice::venue_offers echantillon={len(rows)}")
if rows:
    print("::notice::colonnes=" + ",".join(rows[0].keys()))
    for r in rows[:4]:
        print("::notice::ex=" + json.dumps(r, ensure_ascii=False, default=str)[:600])
cnt = ps._request("GET", "venue_offers", params={"select": "kind,is_active", "limit": "5000"}) or []
import collections
print("::notice::kinds=" + json.dumps(collections.Counter(f"{r.get('kind')}/{r.get('is_active')}" for r in cnt)))
