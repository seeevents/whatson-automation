"""Pose le marqueur offer-wo:<id> sur les offres deja creees par l'automatisation (last_verified_at renseigne, depuis le 13/11)."""
import os, sys
sys.path.insert(0, os.getcwd())
from src import dedup, offers, publication_supabase as ps
write = os.environ.get("CONVERT_WRITE", "false").lower() == "true"
venues = {v["id_venue"]: v["name"] for v in (ps._request("GET", "venues", params={"select": "id_venue,name", "limit": "5000"}) or [])}
rows = ps._request("GET", "venue_offers", params={"select": "id_offer,id_venue,title,last_verified_at,created_at", "created_at": "gte.2026-11-13T00:00:00Z", "last_verified_at": "not.is.null"}) or []
for r in rows:
    done = dedup.already_processed(f"offer-wo:{r['id_offer']}")
    print(f"::notice::{'deja' if done else ('marquee' if write else 'a marquer')} | {venues.get(r['id_venue'])} | {r['title']} | cree {r['created_at'][:16]}")
    if write and not done:
        offers._mark_created(r["id_offer"])
