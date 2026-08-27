#!/usr/bin/env python3
"""
Vide la table Events_Tracking - lance chaque matin AVANT le premier run
(Brique 3), pour que l'equipe voie chaque jour uniquement les events
traites du jour meme.

Protection (ajoutee le 27 aout 2026 suite a un incident) : si des
enregistrements d'AUJOURD'HUI (heure Bali) sont deja presents dans la
table, cela signifie que le pipeline du jour a deja tourne (cron en
retard/desordonne) - dans ce cas, on REFUSE de vider pour ne pas effacer
le travail du jour, et on log un avertissement plutot que de supprimer
silencieusement.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from config import settings
from src import airtable_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.clear_tracking")


def main() -> int:
    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    records = airtable_client.search_records(settings.AIRTABLE_TABLE_TRACKING, formula="TRUE()", max_records=5)
    today_bali = datetime.now(settings.BALI_TZ).date()
    for record in records:
        created = record.get("createdTime", "")
        if not created:
            continue
        try:
            created_date = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(settings.BALI_TZ).date()
        except ValueError:
            continue
        if created_date == today_bali:
            logger.warning(
                "REFUS de vider Events_Tracking : des lignes d'AUJOURD'HUI (%s) sont deja presentes "
                "(le pipeline du jour a probablement deja tourne, cron en retard/desordonne). "
                "Nettoyage annule pour ne pas effacer le travail du jour.",
                today_bali,
            )
            return 0

    deleted = airtable_client.delete_all_records(settings.AIRTABLE_TABLE_TRACKING)
    logger.info("Events_Tracking videe: %d ligne(s) supprimee(s)", deleted)
    return 0


if __name__ == "__main__":
    sys.exit(main())

