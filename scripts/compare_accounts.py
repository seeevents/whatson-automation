"""Decouverte + comparaison read-only : venues Supabase vs InstaCheck."""
import collections, json, os, sys
sys.path.insert(0, os.getcwd())
from src import publication_supabase as ps

rows = ps._request("GET", "venues", params={
    "select": "name,instagram_url,scrape_frequency,scrape_days,scrape_batch,client_type,is_hidden",
    "limit": "5000"})
print(f"::notice::venues total={len(rows)}")
c = collections.Counter
print("::notice::freq=" + json.dumps(c(str(r.get("scrape_frequency")) for r in rows), ensure_ascii=False)[:400])
print("::notice::days=" + json.dumps(c(json.dumps(r.get("scrape_days")) for r in rows).most_common(12), ensure_ascii=False)[:600])
print("::notice::batch=" + json.dumps(c(str(r.get("scrape_batch")) for r in rows)))
print("::notice::client_type=" + json.dumps(c(str(r.get("client_type")) for r in rows)))
print("::notice::hidden=" + json.dumps(c(str(r.get("is_hidden")) for r in rows)))

def handle(u): return ps._normalize_handle(u or "")
sb = {}
for r in rows:
    if r.get("scrape_frequency") and r.get("instagram_url"):
        sb.setdefault(handle(r["instagram_url"]), []).append(r)
print(f"::notice::supabase a scraper={len(sb)} handles")

try:
    from src import accounts
    ic = {handle(a.instagram_url) for a in accounts.get_todays_accounts(all_weekdays=True)}
except Exception as exc:
    print(f"::warning::InstaCheck indisponible: {type(exc).__name__}")
    sys.exit(0)
print(f"::notice::instacheck={len(ic)} handles")
print("::notice::instacheck_absent_supabase=" + ",".join(sorted(ic - set(sb)))[:900])
print("::notice::supabase_absent_instacheck=" + ",".join(sorted(set(sb) - ic))[:900])
