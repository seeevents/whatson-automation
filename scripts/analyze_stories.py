"""Lecture seule : combien de stories ont reellement produit des events ? (fenetre avant la panne Gemini du 11/11)."""
import collections, json, os, sys
sys.path.insert(0, os.getcwd())
from config import settings
from src import airtable_client as at

START, END = "2026-10-12", "2026-11-10"
win = f"IS_AFTER(CREATED_TIME(), DATETIME_PARSE('{START}')), IS_BEFORE(CREATED_TIME(), DATETIME_PARSE('{END}'))"

seen = at.search_records(settings.AIRTABLE_TABLE_DEDUP,
    formula=f"AND(FIND('/stories/', {{Instagram Item ID}}), {win})", max_records=100000)
posts_seen = at.search_records(settings.AIRTABLE_TABLE_DEDUP,
    formula=f"AND(NOT(FIND('/stories/', {{Instagram Item ID}})), FIND('/p/', {{Instagram Item ID}}), {win})", max_records=100000)
print(f"::notice::fenetre {START} -> {END} | stories vues={len(seen)} | posts vus={len(posts_seen)}")

evs = at.search_records(settings.AIRTABLE_TABLE_EVENTS,
    formula=f"AND(FIND('[GEMINI VISION]', {{Alerte}}), {win})", max_records=100000)
by_status = collections.Counter()
by_venue = collections.defaultdict(collections.Counter)
for r in evs:
    f = r["fields"]
    st = f.get("Statut")
    st = st.get("name") if isinstance(st, dict) else st
    by_status[st] += 1
    by_venue[f.get("Venue Name", "?")][st] += 1
print(f"::notice::events issus de stories (lignes Airtable)={len(evs)} | par statut={dict(by_status)}")
good = {v: c for v, c in by_venue.items() if c.get("Validé", 0) + c.get("Rapporté", 0) > 0}
print(f"::notice::venues avec >=1 event valide issu d'une story={len(good)} sur {len(by_venue)} venues ayant produit au moins une ligne")
top = sorted(good.items(), key=lambda x: -(x[1].get("Validé", 0) + x[1].get("Rapporté", 0)))[:15]
for v, c in top:
    print(f"::notice::top | {v} | valides={c.get('Validé',0)+c.get('Rapporté',0)} | ignores={c.get('Ignoré',0)}")
valid_total = by_status.get("Validé", 0) + by_status.get("Rapporté", 0)
print(f"::notice::events valides issus de stories={valid_total} | de posts (toutes sources)=voir ci-dessous")

allev = at.search_records(settings.AIRTABLE_TABLE_EVENTS, formula=f"AND({win})", max_records=100000)
tot = collections.Counter()
for r in allev:
    st = r["fields"].get("Statut"); st = st.get("name") if isinstance(st, dict) else st
    tot[st] += 1
print(f"::notice::toutes lignes Airtable sur la fenetre={len(allev)} | par statut={dict(tot)}")
