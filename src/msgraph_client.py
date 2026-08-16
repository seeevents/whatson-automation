"""
Connecteur Microsoft Graph - remplace le module microsoft-excel:listWorksheetRows
de Make. Lit la feuille InstaCheck.xlsx sur SharePoint via l'API Graph
(authentification par client credentials - pas d'interaction utilisateur).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from config import settings

logger = logging.getLogger("whatson.msgraph")

TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
MAX_RETRIES = 3

_cached_token: str | None = None
_cached_token_expiry: float = 0.0


class MSGraphError(Exception):
    """Erreur lors d'un appel a l'API Microsoft Graph."""


def _get_access_token() -> str:
    """Recupere (et met en cache) un token d'acces via client credentials flow."""
    global _cached_token, _cached_token_expiry

    if _cached_token and time.time() < _cached_token_expiry - 60:
        return _cached_token

    if not (settings.MS_CLIENT_ID and settings.MS_CLIENT_SECRET and settings.MS_TENANT_ID):
        raise MSGraphError(
            "MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET / MICROSOFT_TENANT_ID manquants."
        )

    url = TOKEN_URL_TEMPLATE.format(tenant=settings.MS_TENANT_ID)
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.MS_CLIENT_ID,
        "client_secret": settings.MS_CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
    }
    resp = requests.post(url, data=data, timeout=30)
    if not resp.ok:
        raise MSGraphError(f"Echec authentification Graph: {resp.status_code} {resp.text[:500]}")

    payload = resp.json()
    _cached_token = payload["access_token"]
    _cached_token_expiry = time.time() + payload.get("expires_in", 3600)
    logger.info("Token Microsoft Graph obtenu (valide %ss)", payload.get("expires_in"))
    return _cached_token


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_get_access_token()}"}


def _request(method: str, url: str, **kwargs) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, headers=_headers(), timeout=60, **kwargs)
            if resp.status_code == 429:
                retry_after_raw = resp.headers.get("Retry-After", "5")
                try:
                    # Retry-After peut contenir plusieurs valeurs separees par virgule
                    # (observe en cas de rate-limit simultane sur plusieurs jobs paralleles)
                    wait = int(retry_after_raw.split(",")[0].strip())
                except (ValueError, AttributeError):
                    wait = 5
                logger.warning("Graph rate-limit (429), retry dans %ss", wait)
                time.sleep(wait)
                continue
            if not resp.ok:
                raise MSGraphError(f"{resp.status_code} {resp.reason}: {resp.text[:500]}")
            return resp.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)
    raise MSGraphError(f"Echec apres {MAX_RETRIES} tentatives: {last_error}") from last_error


def _find_instacheck_item_id() -> str:
    """Cherche InstaCheck.xlsx par nom dans le drive du site (evite de dependre
    d'IDs internes opaques)."""
    url = f"{GRAPH_BASE}/sites/{settings.MS_SITE_ID}/drive/root/search(q='{settings.MS_INSTACHECK_FILENAME}')"
    data = _request("GET", url)
    items = data.get("value", [])
    for item in items:
        if item.get("name") == settings.MS_INSTACHECK_FILENAME:
            return item["id"]
    raise MSGraphError(f"Fichier '{settings.MS_INSTACHECK_FILENAME}' introuvable sur le site.")


def get_instacheck_data() -> tuple[list[list[Any]], list[list[Any]]]:
    """
    Retourne (values, formulas) de la feuille InstaCheck (usedRange).
    Les formules sont necessaires car la colonne H contient des liens
    =HYPERLINK("url"; "texte") - la valeur affichee n'est que le texte
    cliquable, l'URL reelle n'existe que dans la formule.
    """
    item_id = _find_instacheck_item_id()
    url = (
        f"{GRAPH_BASE}/sites/{settings.MS_SITE_ID}/drive/items/{item_id}"
        f"/workbook/worksheets('{settings.MS_INSTACHECK_WORKSHEET}')/usedRange"
        f"?$select=values,formulas"
    )
    data = _request("GET", url)
    values = data.get("values", [])
    formulas = data.get("formulas", [])
    logger.info("InstaCheck: %d ligne(s) lue(s) (dont en-tete)", len(values))
    return values, formulas
