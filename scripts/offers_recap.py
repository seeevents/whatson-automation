#!/usr/bin/env python3
"""Recap (lecture seule) : offres non reconfirmees depuis 3 passages (a signaler au BO, sans les modifier)."""
import os, sys
sys.path.insert(0, os.getcwd())
from src import offers, publication_supabase as ps
venues = {v["id_venue"]: v["name"] for v in (ps._request("GET", "venues", params={"select": "id_venue,name", "limit": "5000"}) or [])}
stale = offers.stale_offers()
print(f"::notice::offres non reconfirmees depuis 3 passages: {len(stale)}")
for r in stale:
    print(f"::notice::{venues.get(r['id_venue'])} | {r['kind']} | {r['title']} | fin {r['end_date']} | derniere verif {r['last_verified_at']} | active={r['is_active']}")
