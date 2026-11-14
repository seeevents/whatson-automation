"""Convertit en 00:00-23:59 les offres INACTIVES a 00:00-00:00 dont les jours sont connus (convention All day du BO).
Essai a blanc par defaut ; ecrit seulement si CONVERT_WRITE=true. Ne touche pas aux jours inconnus ni aux offres actives."""
import os, sys
sys.path.insert(0, os.getcwd())
from src import publication_supabase as ps
write = os.environ.get("CONVERT_WRITE", "false").lower() == "true"
venues = {v["id_venue"]: v["name"] for v in (ps._request("GET", "venues", params={"select": "id_venue,name", "limit": "5000"}) or [])}
rows = ps._request("GET", "venue_offers", params={"select": "id_offer,id_venue,title,days_of_week,start_time,end_time,is_active", "is_active": "eq.false", "start_time": "eq.00:00:00", "end_time": "eq.00:00:00", "limit": "500"}) or []
n = 0
for r in rows:
    if not r.get("days_of_week"):
        print(f"::notice::inchangee (jours inconnus) | {venues.get(r['id_venue'])} | {r['title']}")
        continue
    print(f"::notice::{'convertie' if write else 'a convertir'} | {venues.get(r['id_venue'])} | {r['title']} | {r['days_of_week']}")
    if write:
        ps._request("PATCH", "venue_offers", params={"id_offer": f"eq.{r['id_offer']}"}, json_body={"end_time": "23:59:00"}, prefer="return=minimal")
    n += 1
print(f"::notice::total {n} ({'ecrit' if write else 'essai a blanc'})")
