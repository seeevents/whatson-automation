import os, sys, collections
sys.path.insert(0, os.getcwd())
from datetime import datetime, timedelta, timezone
from config import settings
from src import airtable_client as at, publication_supabase as ps
bali = timezone(timedelta(hours=8))
day = datetime.now(bali).strftime("%Y-%m-%d")
d0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=bali).astimezone(timezone.utc).isoformat()
rows = at.search_records(settings.AIRTABLE_TABLE_EVENTS,
    formula=f"IS_AFTER(CREATED_TIME(), DATETIME_PARSE('{d0}'))", max_records=3000)
st = collections.Counter(str(r["fields"].get(settings.FLD_STATUT)) for r in rows)
story = sum(1 for r in rows if "GEMINI VISION" in str(r["fields"].get(settings.FLD_ALERTE) or ""))
print(f"::notice::{day} Airtable collectes: {len(rows)} (stories={story}) statuts={dict(st)}")
for off in (0, 1):
    a = (datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=bali) - timedelta(days=off)).astimezone(timezone.utc).isoformat()
    b = (datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=bali) + timedelta(days=1 - off)).astimezone(timezone.utc).isoformat()
    try:
        ev = ps._request("GET", "events", params=[("select", "id_event,source_type,created_at"), ("created_at", f"gte.{a}"), ("created_at", f"lt.{b}"), ("limit", "2000")]) or []
        print(f"::notice::Supabase events crees (jour -{off}): {len(ev)} par source_type={dict(collections.Counter(e.get('source_type') for e in ev))}")
    except Exception as exc:
        print(f"::notice::Supabase erreur: {str(exc)[:200]}")
