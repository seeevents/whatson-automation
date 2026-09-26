#!/usr/bin/env python3
"""
Test isole de la publication V2 (Supabase) UNIQUEMENT : ne touche PAS a
GoodBarber ni au statut Airtable. Accepte une ligne Airtable de N'IMPORTE
QUEL statut (y compris deja "Rapporte"). Relancable sans risque : si l'event
existe deja cote V2, il est mis a jour au lieu d'etre duplique.
Sans heure precise (pas d'appel Claude ici), l'event est place a 20h Bali.
Usage: python scripts/test_publication_supabase.py <record_id>
"""
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from src import airtable_client, publication_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.test_publication_supabase")


def main() -> int:
    if len(sys.argv) < 2 or not re.fullmatch(r"rec[A-Za-z0-9]{14}", sys.argv[1]):
        logger.error("Usage: python scripts/test_publication_supabase.py <record_id> (ex: recAbCdEfGhIjKlMn)")
        return 1
    record_id = sys.argv[1]

    records = airtable_client.search_records(
        settings.AIRTABLE_TABLE_EVENTS, formula=f"RECORD_ID()='{record_id}'", max_records=1
    )
    if not records:
        logger.error("ID '%s' introuvable.", record_id)
        return 1

    fields = records[0]["fields"]
    logger.info(
        "MODE TEST V2 seulement - venue=%r instagram=%r titre=%r date=%r",
        fields.get(settings.FLD_VENUE_NAME), fields.get(settings.FLD_INSTAGRAM),
        fields.get(settings.FLD_TITRE), fields.get(settings.FLD_DATE),
    )

    result = publication_supabase.publish_to_supabase(records[0], None)
    logger.info("Resultat V2: %s", result)
    # Code retour non nul si rien n'a ete ecrit a cause d'un probleme (pour que le run GitHub passe au rouge).
    return 0 if result["status"] in ("created", "updated", "skipped_manual_exists") else 1


if __name__ == "__main__":
    sys.exit(main())
