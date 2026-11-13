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
COL_BATCH_NUMBER = 17  # R - numero de batch assigne (1 a 8 sur Make), PAS un flag actif/inactif


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


def _accounts_from_supabase(batch_number: str | None, all_weekdays: bool) -> list[Account]:
    """Liste des comptes depuis la table `venues` du back-office V2.

    Regles (confirmees par l'equipe BO) : client_type = not_a_client (= flag
    "Claude" d'InstaCheck), scrape_frequency everyday / once_a_week, URL
    Instagram non vide, scrape_batch 1 a 8, et jour courant dans scrape_days
    (sauf frequence everyday ou all_weekdays)."""
    from src import publication_supabase as ps

    rows = ps._request("GET", "venues", params={
        "select": "name,instagram_url,scrape_frequency,scrape_days,scrape_batch,client_type",
        "client_type": "eq.not_a_client",
        "limit": "5000",
    }) or []
    today = datetime.now(settings.BALI_TZ).strftime("%A").lower()
    accounts: list[Account] = []
    seen: set[str] = set()
    for r in rows:
        freq = (r.get("scrape_frequency") or "").strip().lower()
        if freq not in ("everyday", "once_a_week"):
            continue
        batch = str(r.get("scrape_batch") or "")
        if batch not in ("1", "2", "3", "4", "5", "6", "7", "8"):
            continue
        if batch_number is not None and batch != batch_number:
            continue
        days = r.get("scrape_days") or []
        if isinstance(days, str):
            days = [d.strip().lower() for d in days.strip("[]").replace('"', "").split(",") if d.strip()]
        days = [str(d).lower() for d in days]
        if not all_weekdays and freq != "everyday" and today not in days:
            continue
        url = (r.get("instagram_url") or "").split("?")[0].strip()
        if not url or url in seen:
            continue
        seen.add(url)
        accounts.append(Account(venue_name=r.get("name") or "", instagram_url=url))
    label = f"batch {batch_number}" if batch_number else "tous batches"
    logger.info("Comptes retenus (Supabase, %s, %s): %d", today, label, len(accounts))
    return accounts


def get_todays_accounts(batch_number: str | None = None, all_weekdays: bool = False) -> list[Account]:
    """
    Source principale : table `venues` Supabase (back-office V2). Si elle est
    indisponible ou renvoie 0 compte, repli sur InstaCheck.xlsx (Microsoft Graph).
    """
    from src import publication_supabase as ps

    if ps._is_configured() and settings.ACCOUNTS_SOURCE != "instacheck":
        try:
            accs = _accounts_from_supabase(batch_number, all_weekdays)
            if accs:
                return accs
            logger.warning("Supabase: 0 compte retenu - repli sur InstaCheck.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Supabase indisponible (%s) - repli sur InstaCheck.", type(exc).__name__)
    return _accounts_from_instacheck(batch_number, all_weekdays)


def _accounts_from_instacheck(batch_number: str | None = None, all_weekdays: bool = False) -> list[Account]:
    """
    Retourne la liste des comptes a traiter aujourd'hui.
    Si batch_number est fourni ("1" a "8"), ne retourne que les comptes de
    CE batch (reproduit le decoupage Make pour permettre l'execution
    parallele des 8 batches). Si None, retourne TOUS les comptes du jour
    tous batches confondus (mode sequentiel complet).
    all_weekdays=True ignore la colonne F (jour de la semaine) : tous les
    comptes actifs, utilise par le passage hebdo des posts epingles.
    """
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
        row_batch_number = cell(COL_BATCH_NUMBER, row)

        if "Claude" not in model:
            continue
        if not all_weekdays and weekday not in ("Everyday", today_weekday):
            continue
        if row_batch_number not in ("1", "2", "3", "4", "5", "6", "7", "8"):
            continue
        if batch_number is not None and row_batch_number != batch_number:
            continue

        venue_name = cell(COL_VENUE_NAME, row)
        hyperlink_formula = cell(COL_INSTAGRAM_URL, row_formulas)
        instagram_url = _extract_url_from_hyperlink_formula(hyperlink_formula)

        if not instagram_url:
            continue

        accounts.append(Account(venue_name=venue_name, instagram_url=instagram_url))

    label = f"batch {batch_number}" if batch_number else "tous batches"
    logger.info("Comptes retenus pour aujourd'hui (%s, %s): %d", today_weekday, label, len(accounts))
    return accounts
