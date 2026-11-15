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


def extract_from_images(
    image_urls: list[str], caption: str = "", published_timestamp: str = ""
) -> dict[str, str]:
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
        "d'un evenement a Bali. "
        f"{('Ce post/story a ete publie le : ' + published_timestamp + '. ') if published_timestamp else ''}"
        "REGLE CRITIQUE - DATE SANS ANNEE PRECISEE (le flyer donne mois+jour seulement, ex: "
        "'Sept 19th-21st', sans annee) : n'utilise JAMAIS l'annee courante par defaut de "
        "maniere automatique. Utilise TOUJOURS la date de publication ci-dessus comme "
        "reference pour deduire l'annee correcte - l'evenement a presque toujours lieu PEU "
        "DE TEMPS APRES la publication (quelques semaines a quelques mois), pas forcement "
        "dans l'annee d'aujourd'hui. Si le post est ancien (publie il y a longtemps) et que "
        "la date mois+jour tombe logiquement dans l'annee DE PUBLICATION, utilise cette "
        "annee-la MEME SI cela rend l'evenement deja passe par rapport a aujourd'hui - "
        "laisse alors la vraie date passee dans le champ date (le systeme en aval la "
        "traitera comme perimee), NE LA DECALE JAMAIS artificiellement vers une annee "
        "future juste pour la rendre 'a venir'. Si l'image donne une annee EXPLICITE, "
        "utilise-la telle quelle (les evenements a Bali se produisent normalement dans le "
        "present/futur proche, annees courantes 2026 et au-dela - ne traite jamais une "
        "annee explicite recente comme suspecte). Si l'image mentionne un jour de la semaine recurrent (ex: EVERY MONDAY), "
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


# ---------------------------------------------------------------------------
# Stories : prompt dedie + images/frames video + textes des stickers
# ---------------------------------------------------------------------------
import os
import subprocess
import tempfile

MAX_VIDEO_BYTES = 40 * 1024 * 1024


def _video_frames_b64(video_url: str, max_frames: int = 4) -> list[str]:
    """Telecharge la video d'une story et en extrait quelques images (ffmpeg)."""
    if not video_url:
        return []
    try:
        resp = requests.get(video_url, timeout=60, stream=True)
        resp.raise_for_status()
        data = b""
        for chunk in resp.iter_content(1024 * 256):
            data += chunk
            if len(data) > MAX_VIDEO_BYTES:
                logger.warning("Video story trop lourde, ignoree")
                return []
    except requests.RequestException as exc:
        logger.warning("Echec telechargement video story: %s", exc)
        return []
    frames: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "v.mp4")
        with open(src, "wb") as fh:
            fh.write(data)
        # une image toutes les 2 s, max_frames images, largeur 720 px
        cmd = ["ffmpeg", "-loglevel", "error", "-i", src, "-vf", "fps=1/2,scale=720:-2",
               "-frames:v", str(max_frames), os.path.join(tmp, "f%02d.jpg")]
        try:
            subprocess.run(cmd, check=True, timeout=90)
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            logger.warning("ffmpeg indisponible/echec: %s", exc)
            return []
        for name in sorted(os.listdir(tmp)):
            if name.endswith(".jpg"):
                with open(os.path.join(tmp, name), "rb") as fh:
                    frames.append(base64.b64encode(fh.read()).decode("utf-8"))
    return frames


def extract_from_story(
    image_urls: list[str],
    video_url: str = "",
    stickers_text: str = "",
    venue_name: str = "",
    published_timestamp: str = "",
) -> dict[str, str]:
    """Analyse d'une story Instagram (image ou video) -> {titre, date, alerte}.
    Pour une video, plusieurs images extraites + l'image de couverture sont envoyees."""
    if not settings.GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY manquant dans l'environnement.")

    parts = []
    for url in image_urls[:1]:
        b64 = _download_image_b64(url)
        if b64:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
    for b64 in _video_frames_b64(video_url):
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
    if not parts:
        return {}

    prompt = (
        "Tu analyses une STORY Instagram (image, ou images extraites d'une video) publiee par "
        f"le lieu/compte '{venue_name}' a Bali. "
        f"{('Publiee le : ' + published_timestamp + ' (heure de Bali). ') if published_timestamp else ''}"
        "Les stories annoncent souvent un evenement du jour ou des prochains jours avec un texte "
        "stylise ou ecrit en surimpression (TONIGHT, THIS SATURDAY, LIVE MUSIC, DJ, LINE-UP, "
        "OPENING, LADIES NIGHT, QUIZ, BRUNCH, PARTY, sport diffuse, etc.). Lis TOUT le texte visible "
        "sur toutes les images, y compris petit, en bordure ou sur un fond charge. "
        "Reponds uniquement si la story annonce un evenement, une soiree, un concert/DJ, une "
        "animation, un tournoi, un evenement sportif diffuse, un atelier, une ouverture, ou une "
        "offre limitee (happy hour, promo) avec un jour/une date. "
        "DATE : convertis les mentions relatives par rapport a la date de publication "
        "('TONIGHT'/'TODAY' = jour de publication, 'TOMORROW' = lendemain, 'THIS FRIDAY' = le "
        "prochain vendredi, 'EVERY SUNDAY' = le prochain dimanche). Sans annee explicite, deduis "
        "l'annee de la date de publication. Si seul le mois+jour est donne, utilise-le. "
        "Si plusieurs jours, la date est le premier jour et le planning complet va dans alerte. "
        "ALERTE : resume en une a trois phrases (en anglais) : artistes/DJ/line-up, horaires, "
        "prix, reservation, lien ou code promo, tout detail utile. "
        "TITRE : nom de l'evenement (pas juste le nom du lieu ou son @compte). "
        "Si la story est un simple repost de photo, un plat/ambiance sans annonce, un remerciement "
        "ou une pub sans evenement identifiable, renvoie des chaines vides pour les trois champs. "
        "Reponds avec UN SEUL objet JSON : "
        '{"titre": "...", "date": "YYYY-MM-DD", "alerte": "..."}'
    )
    if stickers_text:
        prompt = f"Textes/liens des stickers de la story : {stickers_text}\n\n{prompt}"
    parts.append({"text": prompt})

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "thinkingConfig": {"thinkingLevel": "low"},
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
        if isinstance(result, list):
            result = result[0] if result else {}
    except json.JSONDecodeError:
        result = {}
        for key in ("titre", "date", "alerte"):
            m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text)
            if m:
                result[key] = m.group(1)
    return {k: (result.get(k) or "") for k in ("titre", "date", "alerte")}
