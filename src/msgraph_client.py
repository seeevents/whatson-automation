"""
Connecteur Microsoft Graph - remplace le module microsoft-excel:listWorksheetRows
de Make. Lit la feuille InstaCheck.xlsx sur SharePoint via l'API Graph
(authentification par client credentials - pas d'interaction utilisateur).
"""
from __future__ import annotations

import base64
import logging
import threading
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
_token_lock = threading.Lock()  # evite les fetchs redondants/concurrents en mode parallele


class MSGraphError(Exception):
    """Erreur lors d'un appel a l'API Microsoft Graph."""


def _get_access_token() -> str:
    """Recupere (et met en cache) un token d'acces via client credentials flow.
    Thread-safe : un seul thread rafraichit le token a la fois, les autres
    attendent puis reutilisent le resultat mis en cache."""
    global _cached_token, _cached_token_expiry

    with _token_lock:
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
            if resp.status_code in (502, 503, 504):
                # Erreurs serveur transitoires (ex: surcharge Microsoft quand
                # plusieurs batches paralleles appellent la meme API en meme
                # temps) - retry avec backoff exponentiel plutot que d'echouer
                # immediatement (observe en production le 23 aout 2026).
                wait = 5 * attempt
                logger.warning(
                    "Graph erreur serveur transitoire (%s), retry dans %ss (tentative %d/%d)",
                    resp.status_code, wait, attempt, MAX_RETRIES,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(wait)
                    continue
                raise MSGraphError(f"{resp.status_code} {resp.reason}: {resp.text[:500]}")
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


def _extract_url_from_formula(formula: str) -> str:
    """Extrait l'URL d'une formule =HYPERLINK("url";"texte")."""
    if not formula or not str(formula).upper().startswith("=HYPERLINK"):
        return ""
    parts = str(formula).split('"')
    return parts[1] if len(parts) >= 2 else ""


def resolve_client_file(venue_name: str) -> dict[str, str] | None:
    """
    Cherche la venue dans la colonne A d'InstaCheck (lignes 9-600), recupere
    le lien de partage vers son fichier client dedie en colonne J, et le
    resout en identifiant reel (drive_id + item_id) via l'API Graph.
    Retourne None si la venue n'est pas trouvee ou si le lien est invalide.
    """
    col_a_url = (
        f"{GRAPH_BASE}/drives/{settings.MS_INSTACHECK_DRIVE_ID}/items/{settings.MS_INSTACHECK_ITEM_ID}"
        f"/workbook/worksheets('{settings.MS_INSTACHECK_WORKSHEET}')/range(address='A9:A600')"
    )
    col_j_url = (
        f"{GRAPH_BASE}/drives/{settings.MS_INSTACHECK_DRIVE_ID}/items/{settings.MS_INSTACHECK_ITEM_ID}"
        f"/workbook/worksheets('{settings.MS_INSTACHECK_WORKSHEET}')/range(address='J9:J600')"
    )
    col_a = _request("GET", col_a_url)
    col_j = _request("GET", col_j_url)

    a_values = [str(row[0]) if row and row[0] is not None else "" for row in col_a.get("values", [])]
    j_formulas = [str(row[0]) if row and row[0] is not None else "" for row in col_j.get("formulas", [])]

    search = venue_name.strip().lower()
    row_index = None
    for i, v in enumerate(a_values):
        if v and search in v.lower():
            row_index = i
            break
    if row_index is None:
        logger.info("resolve_client_file: venue '%s' non trouvee dans InstaCheck", venue_name)
        return None

    j_formula = j_formulas[row_index] if row_index < len(j_formulas) else ""
    extracted_url = _extract_url_from_formula(j_formula)
    if not extracted_url:
        logger.info("resolve_client_file: pas de lien de partage pour '%s'", venue_name)
        return None

    b64 = base64.b64encode(extracted_url.encode()).decode()
    b64 = b64.replace("+", "-").replace("/", "_").rstrip("=")
    share_token = f"u!{b64}"

    try:
        result = _request("GET", f"{GRAPH_BASE}/shares/{share_token}/driveItem")
    except MSGraphError as exc:
        logger.warning("resolve_client_file: echec resolution partage pour '%s': %s", venue_name, exc)
        return None

    return {
        "name": result.get("name", ""),
        "item_id": result.get("id", ""),
        "drive_id": (result.get("parentReference") or {}).get("driveId", ""),
        "weburl": result.get("webUrl", ""),
    }


def report_event_to_client(drive_id: str, item_id: str, titre_event: str, date_event: str) -> bool:
    """
    Ecrit une nouvelle ligne d'evenement dans l'onglet PLANNING du fichier
    client resolu (premiere ligne vide entre B17 et B60). Retourne False
    en cas d'echec (sans lever d'exception - best-effort, comme sur Make).
    """
    try:
        range_url = (
            f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
            f"/workbook/worksheets('PLANNING')/range(address='B17:B60')"
        )
        result = _request("GET", range_url)
        value_types = result.get("valueTypes", [])
        flat = [row[0] if row else "Empty" for row in value_types]
        non_empty_count = sum(1 for v in flat if v != "Empty")
        target_row = non_empty_count + 17

        write_url = (
            f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
            f"/workbook/worksheets('PLANNING')/range(address='A{target_row}:I{target_row}')"
        )
        body = {"values": [["Event", titre_event, date_event, "", "", "", "", "", False]]}
        _request("PATCH", write_url, json=body)
        return True
    except MSGraphError as exc:
        logger.warning("report_event_to_client: echec ecriture: %s", exc)
        return False
