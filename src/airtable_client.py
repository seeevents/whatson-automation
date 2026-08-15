"""
Connecteur Airtable minimal - remplace les modules airtable:* de Make.
Utilise l'API REST officielle Airtable directement (pas de dépendance tierce).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from config.settings import AIRTABLE_API_KEY, AIRTABLE_BASE_ID

logger = logging.getLogger("whatson.airtable")

BASE_URL = "https://api.airtable.com/v0"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


class AirtableError(Exception):
    """Erreur lors d'un appel à l'API Airtable."""


def _headers() -> dict[str, str]:
    if not AIRTABLE_API_KEY:
        raise AirtableError("AIRTABLE_API_KEY manquant dans l'environnement.")
    return {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json",
    }


def _request(method: str, url: str, **kwargs) -> dict[str, Any]:
    """Requête HTTP avec retry simple sur erreurs transitoires (429, 5xx)."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, headers=_headers(), timeout=30, **kwargs)
            if resp.status_code == 429:
                wait = RETRY_BACKOFF_SECONDS * attempt
                logger.warning("Airtable rate-limit (429), retry dans %ss (tentative %s/%s)", wait, attempt, MAX_RETRIES)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise AirtableError(f"Echec après {MAX_RETRIES} tentatives: {last_error}") from last_error


def search_records(
    table_id: str,
    formula: str,
    fields: list[str] | None = None,
    max_records: int = 500,
) -> list[dict[str, Any]]:
    """
    Recherche des enregistrements avec pagination automatique (Airtable limite
    à 100 par page ; on enchaîne les pages via `offset` jusqu'à max_records).
    """
    url = f"{BASE_URL}/{AIRTABLE_BASE_ID}/{table_id}"
    records: list[dict[str, Any]] = []
    offset = None

    while True:
        params: dict[str, Any] = {
            "filterByFormula": formula,
            "pageSize": min(100, max_records - len(records)),
            "returnFieldsByFieldId": "true",  # sinon Airtable renvoie les champs par NOM, pas par ID
        }
        if fields:
            params["fields[]"] = fields
        if offset:
            params["offset"] = offset

        data = _request("GET", url, params=params)
        records.extend(data.get("records", []))

        offset = data.get("offset")
        if not offset or len(records) >= max_records:
            break

    logger.info("search_records(%s): %d enregistrement(s) trouvé(s)", table_id, len(records))
    return records[:max_records]


def update_record(table_id: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Met à jour un enregistrement existant (PATCH - ne touche que les champs fournis)."""
    url = f"{BASE_URL}/{AIRTABLE_BASE_ID}/{table_id}/{record_id}"
    return _request("PATCH", url, json={"fields": fields})


def create_record(table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Crée un nouvel enregistrement."""
    url = f"{BASE_URL}/{AIRTABLE_BASE_ID}/{table_id}"
    return _request("POST", url, json={"fields": fields})


def batch_update_records(table_id: str, updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Met à jour jusqu'à 10 enregistrements par appel (limite Airtable).
    `updates` = [{"id": "recXXX", "fields": {...}}, ...]
    """
    url = f"{BASE_URL}/{AIRTABLE_BASE_ID}/{table_id}"
    results: list[dict[str, Any]] = []
    for i in range(0, len(updates), 10):
        chunk = updates[i : i + 10]
        data = _request("PATCH", url, json={"records": chunk})
        results.extend(data.get("records", []))
    return results
