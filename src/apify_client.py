"""
Connecteur Apify - remplace apify:runActorNew + apify:fetchDatasetItems de Make.
Utilise l'endpoint "run-sync-get-dataset-items" qui fait les deux en un seul
appel (lance l'acteur ET renvoie les items du dataset directement).
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from config import settings

logger = logging.getLogger("whatson.apify")

BASE_URL = "https://api.apify.com/v2"
TIMEOUT = 120


class ApifyError(Exception):
    """Erreur lors d'un appel a l'API Apify."""


def _run_sync_get_dataset_items(actor_id: str, input_body: dict[str, Any]) -> list[dict[str, Any]]:
    if not settings.APIFY_API_TOKEN:
        raise ApifyError("APIFY_API_TOKEN manquant dans l'environnement.")

    url = f"{BASE_URL}/acts/{actor_id}/run-sync-get-dataset-items"
    params = {"token": settings.APIFY_API_TOKEN}
    try:
        resp = requests.post(url, params=params, json=input_body, timeout=TIMEOUT)
        if not resp.ok:
            raise ApifyError(f"{resp.status_code} {resp.reason}: {resp.text[:500]}")
        return resp.json()
    except requests.RequestException as exc:
        raise ApifyError(f"Erreur reseau: {exc}") from exc


def scrape_posts(instagram_url: str, limit: int = 6) -> list[dict[str, Any]]:
    """Scrape les derniers posts d'un compte Instagram.
    onlyPostsNewerThan='2 days' : evite de re-payer/re-telecharger des posts
    deja vus lors des scrapes precedents (le scraping tourne quotidiennement,
    2 jours de marge absorbe les decalages horaires/de planning sans rien
    manquer). Reduit resultsLimit de 12 a 6 (levier cout Apify, 26 aout 2026)."""
    input_body = {
        "directUrls": [instagram_url],
        "resultsType": "posts",
        "resultsLimit": limit,
        "onlyPostsNewerThan": "2 days",
        "addParentData": False,
    }
    try:
        items = _run_sync_get_dataset_items(settings.APIFY_ACTOR_POSTS, input_body)
    except ApifyError as exc:
        logger.error("Echec scraping posts pour %s: %s", instagram_url, exc)
        return []
    logger.info("Posts scrapes pour %s: %d item(s)", instagram_url, len(items))
    return items


def scrape_stories(username: str, limit: int = 20) -> list[dict[str, Any]]:
    """Scrape les stories actives d'un compte Instagram (par username, pas URL)."""
    input_body = {"usernames": [username], "resultsType": "stories", "limit": limit}
    try:
        items = _run_sync_get_dataset_items(settings.APIFY_ACTOR_STORIES, input_body)
    except ApifyError as exc:
        logger.error("Echec scraping stories pour %s: %s", username, exc)
        return []
    logger.info("Stories scrapees pour %s: %d item(s)", username, len(items))
    return items
