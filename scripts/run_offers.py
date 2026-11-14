#!/usr/bin/env python3
"""Offres recurrentes (happy hours / promos). Essai a blanc sauf OFFERS_WRITE_ENABLED=true."""
import json, logging, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings
from src import offers

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

def main() -> int:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else offers.LOOKBACK_DAYS
    results = offers.run(lookback_days=days)
    mode = "ECRITURE" if settings.OFFERS_WRITE_ENABLED else "ESSAI A BLANC"
    print(f"::notice::Offres ({mode}): {dict(Counter(r['action'] for r in results))}")
    for r in results:
        if r["action"] in ("create", "update", "update_verified_only", "skip_venue", "held", "error"):
            o = r.get("offer") or {}
            line = {k: o.get(k) for k in ("kind", "title", "description", "days_of_week", "start_time", "end_time", "start_date", "end_date", "is_active")}
            print(f"::notice::{r['action']} | {r.get('note','')} | {json.dumps(line, ensure_ascii=False, default=str)}"[:900])
    return 0

if __name__ == "__main__":
    sys.exit(main())
