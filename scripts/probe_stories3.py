import os, sys, collections
sys.path.insert(0, os.getcwd())
from config import settings
from src import airtable_client as at
for d0, d1 in (("2026-11-13", "2026-11-14"), ("2026-11-14", "2026-11-15")):
    rows = at.search_records(settings.AIRTABLE_TABLE_EVENTS,
        formula=f"AND(FIND('GEMINI VISION', {{{settings.FLD_ALERTE}}}), IS_AFTER(CREATED_TIME(), DATETIME_PARSE('{d0}')), IS_BEFORE(CREATED_TIME(), DATETIME_PARSE('{d1}')))",
        max_records=1500)
    st = collections.Counter(str(r["fields"].get(settings.FLD_STATUT)) for r in rows)
    empt = sum(1 for r in rows if not r["fields"].get(settings.FLD_TITRE))
    print(f"::notice::{d0}: story rows={len(rows)} titre vide={empt} statuts={dict(st)}")
