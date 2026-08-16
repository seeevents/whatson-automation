"""
Dedoublonnage - remplace la recherche sur la table tblITBraE4pexB4Cy dans Make.
Avant d'extraire un post/story, on verifie s'il a deja ete traite (evite de
re-analyser le meme contenu a chaque scrape quotidien).
"""
from __future__ import annotations

import logging
from datetime import datetime

from config import settings
from src import airtable_client

logger = logging.getLogger("whatson.dedup")


def already_processed(item_url: str) -> bool:
    """Retourne True si cet item (post ou story) a deja ete traite."""
    # Echappe les apostrophes pour la formule Airtable
    safe_url = item_url.replace("'", "\\'")
    records = airtable_client.search_records(
        settings.AIRTABLE_TABLE_DEDUP,
        formula=f"{{Instagram Item ID}} = '{safe_url}'",
        max_records=1,
    )
    return len(records) > 0


def mark_processed(item_url: str) -> None:
    """Marque cet item comme traite pour ne jamais le re-analyser."""
    airtable_client.create_record(
        settings.AIRTABLE_TABLE_DEDUP,
        {
            settings.FLD_DEDUP_URL: item_url,
            settings.FLD_DEDUP_DATE: datetime.now(settings.BALI_TZ).strftime("%Y-%m-%d %H:%M"),
        },
    )
