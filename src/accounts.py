"""
Lit la liste des comptes Instagram a scraper aujourd'hui depuis InstaCheck.xlsx,
en reproduisant exactement le filtre du module 5 du blueprint Make :
- colonne B contient "Claude"
- colonne F = "Everyday" OU = le jour de la semaine actuel (anglais, ex: "Monday")
- colonne R = "1"
- URL Instagram extraite de la formule HYPERLINK en colonne H, sans les
  parametres de requete (tout ce qui suit un "?")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from config import settings
from src import msgraph_client

logger = logging.getLogger("whatson.accounts")

COL_VENUE_NAME = 0   # A
COL_MODEL = 1        # B
COL_WEEKDAY = 5      # F
COL_INSTAGRAM_URL = 7  # H
COL_ACTIVE = 17       # R


@dataclass
class Account:
    venue_name: str
    instagram_url: str


def _extract_url_from_hyperlink_formula(formula: str) -> str:
    """Extrait l'URL d'une formule =HYPERLINK("url";"texte"), et retire
    tout parametre de requete (?...) comme le fait Make."""
    if not formula or not formula.upper().startswith("=HYPERLINK"):
        return ""
    parts = formula.split('"')
    if len(parts) < 2:
        return ""
    url = parts[1]
    return url.split("?")[0]


def get_todays_accounts() -> list[Account]:
    """Retourne la liste des comptes a traiter aujourd'hui."""
    values, formulas = msgraph_client.get_instacheck_data()
    if not values:
        return []

    today_weekday = datetime.now(settings.BALI_TZ).strftime("%A")  # ex: "Monday"

    accounts: list[Account] = []
    # Ligne 0 = en-tetes, on saute
    for i in range(1, len(values)):
        row = values[i]
        row_formulas = formulas[i] if i < len(formulas) else []

        def cell(idx: int, source: list) -> str:
            return str(source[idx]) if idx < len(source) and source[idx] is not None else ""

        model = cell(COL_MODEL, row)
        weekday = cell(COL_WEEKDAY, row)
        active = cell(COL_ACTIVE, row)

        if "Claude" not in model:
            continue
        if weekday not in ("Everyday", today_weekday):
            continue
        if active != "1":
            continue

        venue_name = cell(COL_VENUE_NAME, row)
        hyperlink_formula = cell(COL_INSTAGRAM_URL, row_formulas)
        instagram_url = _extract_url_from_hyperlink_formula(hyperlink_formula)

        if not instagram_url:
            continue

        accounts.append(Account(venue_name=venue_name, instagram_url=instagram_url))

    logger.info("Comptes retenus pour aujourd'hui (%s): %d", today_weekday, len(accounts))
    return accounts
