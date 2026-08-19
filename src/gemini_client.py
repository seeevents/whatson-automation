"""
Connecteur Gemini Vision - remplace les appels HTTP directs vers
generativelanguage.googleapis.com que Make faisait pour le fallback OCR.
"""
from __future__ import annotations

import base64
import json
import logging
import re

import requests

from config import settings

logger = logging.getLogger("whatson.gemini")

API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TIMEOUT = 120


class GeminiError(Exception):
    """Erreur lors d'un appel a l'API Gemini."""


def _download_image_b64(image_url: str) -> str | None:
    try:
        resp = requests.get(image_url, timeout=30)
        resp.raise_for_status()
        return base64.b64encode(resp.content).decode("utf-8")
    except requests.RequestException as exc:
        logger.warning("Echec telechargement image %s: %s", image_url, exc)
        return None


def extract_from_images(image_urls: list[str], caption: str = "") -> dict[str, str]:
    """
    Envoie une ou plusieurs images (+ legende optionnelle) a Gemini Vision
    pour en extraire {titre, date, alerte}. Retourne un dict vide si echec
    total (aucune image telechargeable ou erreur API).
    """
    if not settings.GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY manquant dans l'environnement.")

    parts = []
    for url in image_urls:
        b64 = _download_image_b64(url)
        if b64:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    if not parts:
        logger.warning("Aucune image telechargeable pour le fallback vision.")
        return {}

    prompt_text = (
        "Tu es un extracteur de donnees d'evenements ultra-precis specialise en lecture "
        "d'images (flyers/stories Instagram, souvent avec texte stylise). Analyse TOUTES "
        "les images fournies (meme carrousel) et la legende si presente. Extrait les infos "
        "d'un evenement a Bali. Les evenements se produisent dans le present/futur proche "
        "(annees courantes 2026 et au-dela) - c'est normal, ne traite jamais une date "
        "recente comme suspecte, et n'ecris JAMAIS une annee anterieure a l'annee en cours "
        "par erreur. Si l'image mentionne un jour de la semaine recurrent (ex: EVERY MONDAY), "
        "calcule la prochaine occurrence de ce jour a partir d'aujourd'hui. Si plusieurs "
        "jours (une image = un jour par exemple), utilise comme date le PREMIER jour, et "
        "detaille TOUT le planning jour par jour dans alerte. "
        "IMPORTANT - PROMOS MENU/PLAT, PAS DES EVENEMENTS : si l'image presente un plat, "
        "cocktail, ou produit du menu (avec son prix, ex: 'Seaside Indulgence IDR 599K') "
        "sans date/jour precis associe a une occasion particuliere, ce n'est PAS un "
        "evenement - laisse le champ date VIDE meme si un horaire d'ouverture general est "
        "mentionne (ex: 'Party starts at 2 PM' comme horaire habituel du lieu, pas une date "
        "d'evenement). N'invente jamais une date pour rendre exploitable une simple promo "
        "de carte/menu. "
        "CAS CALENDRIER MULTI-EVENEMENTS : si l'image est un calendrier montrant plusieurs "
        "soirees/evenements differents sur UNE SEMAINE, prefixe le titre par 'This Week at "
        "[nom de la venue]' (ex: 'This Week at Sunset Bar'), utilise comme date le premier "
        "jour du calendrier a partir d'aujourd'hui, et liste le programme complet jour par "
        "jour dans alerte. Si le calendrier couvre UN MOIS entier, prefixe plutot le titre "
        "par 'This Month at [nom de la venue]', meme logique pour la date et le detail en "
        "alerte. Si aucune date lisible, mets une chaine vide pour date. Reponds avec UN SEUL "
        "objet JSON (PAS un tableau, pas de crochets [ ] autour), format exact : "
        '{"titre": "...", "date": "YYYY-MM-DD", "alerte": "..."}'
    )
    if caption:
        prompt_text = f"Legende du post : {caption}\n\n{prompt_text}"

    parts.append({"text": prompt_text})

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "thinkingConfig": {"thinkingLevel": "minimal"},
            "responseMimeType": "application/json",
        },
    }
    url = API_URL_TEMPLATE.format(model=settings.GEMINI_MODEL)
    headers = {"Content-Type": "application/json", "x-goog-api-key": settings.GEMINI_API_KEY}

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
        if not resp.ok:
            raise GeminiError(f"{resp.status_code} {resp.reason}: {resp.text[:500]}")
        data = resp.json()
    except requests.RequestException as exc:
        raise GeminiError(f"Erreur reseau: {exc}") from exc

    try:
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise GeminiError(f"Reponse Gemini inattendue: {data}") from exc

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        # Filet de securite: extraction par regex si le JSON n'est pas strictement valide
        result = {}
        for key in ("titre", "date", "alerte"):
            m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text)
            if m:
                result[key] = m.group(1)

    return {
        "titre": result.get("titre", ""),
        "date": result.get("date", ""),
        "alerte": result.get("alerte", ""),
    }
