#!/usr/bin/env python3
"""Passage hebdomadaire des offres (happy hours / promos) pour un batch. Usage: run_offers_scrape.py [batch]"""
import json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logging
from config import settings
from src import apify_client, offers_scrape

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

def main() -> int:
    batch = sys.argv[1] if len(sys.argv) > 1 else None
    venues = offers_scrape.todays_venues(batch)
    results = offers_scrape.run(batch)
    mode = "ECRITURE" if settings.OFFERS_WRITE_ENABLED else "ESSAI A BLANC"
    st = apify_client.STATS
    print(f"::notice::offres batch {batch} ({mode}): {len(venues)} venues, scrapes={st['calls']}, erreurs_apify={st['errors']}, posts={st['items']}, {dict(Counter(r['action'] for r in results))}")
    for r in results:
        if r["action"] in ("create", "update", "update_verified_only", "skip_venue", "held", "error"):
            o = r.get("offer") or {}
            line = {k: o.get(k) for k in ("kind", "title", "days_of_week", "start_time", "end_time", "start_date", "end_date", "is_active")}
            print(f"::notice::{r['action']} | {r.get('venue','')} | {r.get('note','')[:120]} | {json.dumps(line, ensure_ascii=False, default=str)}"[:800])
    return 0

if __name__ == "__main__":
    sys.exit(main())
