"""Rehberge les images Instagram brutes des offres creees par WO (best-effort). Lecture + PATCH image_url uniquement."""
import os, sys
sys.path.insert(0, os.getcwd())
from datetime import datetime, timedelta, timezone
from src import publication_supabase as ps
since = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
rows = ps._request("GET", "venue_offers", params={"select": "id_offer,image_url,title", "created_at": f"gte.{since}"}) or []
fixed = failed = 0
for r in rows:
    url = r.get("image_url") or ""
    if not url or "supabase" in url:
        continue
    new, note = ps._rehost_image(url)
    if note:
        failed += 1
        print(f"::warning::{r['title']}: {note}")
        continue
    ps._request("PATCH", "venue_offers", params={"id_offer": f"eq.{r['id_offer']}"}, json_body={"image_url": new}, prefer="return=minimal")
    fixed += 1
print(f"::notice::images rehebergees={fixed} echecs={failed}")
