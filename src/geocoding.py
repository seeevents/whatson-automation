"""
Connecteur Google Geocoding API - resout un nom de venue (+ "Bali") en
adresse formatee + coordonnees GPS, pour eviter que les nouveaux events
GoodBarber heritent de coordonnees 0,0 (probleme connu, deja present du
temps de Make : "un nouvel event herite de coordonnees 0,0 qu'il faudrait
corriger manuellement").
"""
from __future__ import annotations

import logging

import requests

from config import settings

logger = logging.getLogger("whatson.geocoding")

API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
TIMEOUT = 15


class GeocodingError(Exception):
    """Erreur lors d'un appel a l'API Google Geocoding."""


def geocode_venue(venue_name: str) -> dict[str, object] | None:
    """
    Cherche "{venue_name}, Bali, Indonesia" et retourne
    {"address": str, "latitude": float, "longitude": float} du premier
    resultat, ou None si aucun resultat / erreur (best-effort, ne doit
    jamais faire echouer la publication).
    """
    if not settings.GOOGLE_MAPS_API_KEY:
        logger.warning("GOOGLE_MAPS_API_KEY manquant - geocodage ignore.")
        return None
    if not venue_name or not venue_name.strip():
        return None

    query = f"{venue_name.strip()}, Bali, Indonesia"
    params = {"address": query, "key": settings.GOOGLE_MAPS_API_KEY}

    try:
        resp = requests.get(API_URL, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Echec geocodage pour '%s': %s", venue_name, exc)
        return None

    status = data.get("status")
    if status != "OK":
        logger.info("Geocodage sans resultat pour '%s' (statut: %s)", venue_name, status)
        return None

    results = data.get("results", [])
    if not results:
        return None

    first = results[0]
    location = first.get("geometry", {}).get("location", {})
    formatted_address = first.get("formatted_address", "")
    lat = location.get("lat")
    lng = location.get("lng")

    if lat is None or lng is None:
        return None

    logger.info("Geocodage OK pour '%s': %s (%s, %s)", venue_name, formatted_address, lat, lng)
    return {"address": formatted_address, "latitude": lat, "longitude": lng}
