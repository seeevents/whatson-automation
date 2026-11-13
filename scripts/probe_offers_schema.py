import os, sys, requests
sys.path.insert(0, os.getcwd())
from config import settings
from src import publication_supabase as ps
r = requests.get(settings.SUPABASE_URL.rstrip("/") + "/rest/v1/", headers=ps._headers(), timeout=60)
d = r.json().get("definitions", {}).get("venue_offers", {})
print("::notice::required=" + ",".join(d.get("required", [])))
for k, v in d.get("properties", {}).items():
    print(f"::notice::col {k}: {v.get('type')} {v.get('format','')} default={v.get('default')}")
