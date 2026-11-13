import os, sys
sys.path.insert(0, os.getcwd())
from datetime import datetime, timedelta, timezone
from src import publication_supabase as ps
since = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
venues = {v["id_venue"]: v["name"] for v in (ps._request("GET", "venues", params={"select": "id_venue,name", "limit": "5000"}) or [])}
rows = ps._request("GET", "venue_offers", params={"select": "id_offer,id_venue,kind,title,days_of_week,start_time,end_time,start_date,end_date,is_active,created_at", "created_at": f"gte.{since}", "order": "created_at.asc"}) or []
print(f"::notice::offres creees depuis 3h: {len(rows)}")
for r in rows:
    print(f"::notice::{r['id_offer']} | {venues.get(r['id_venue'])} | {r['kind']} | {r['title']} | {r['days_of_week']} | {r['start_time']}-{r['end_time']} | {r['start_date']}->{r['end_date']} | {r['is_active']}")
