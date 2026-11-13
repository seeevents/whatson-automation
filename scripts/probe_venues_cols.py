import os, sys, json
sys.path.insert(0, os.getcwd())
from src import publication_supabase as ps
rows = ps._request("GET", "venues", params={"select": "*", "limit": "1"}) or []
print("::notice::venues_cols=" + ",".join(rows[0].keys()))
