"""
Module d'extraction Brique 3 - portage des scenarios Make
"WhatsOn - Brique 3 - Collecte & Analyse - Batch N" / "Integration Apify
Direct - Batch N new". Traite un compte Instagram : scrape posts + stories,
extrait les infos d'evenement (texte pour posts, vision pour stories et
posts sans date), ecrit dans Airtable.
"""
from __future__ import annotations

import logging
from datetime import datetime

from config import settings
from src import accounts, airtable_client, apify_client, claude_client, dedup, gemini_client

logger = logging.getLogger("whatson.extraction")

POST_EXTRACTION_SYSTEM_PROMPT = """Tu es un extracteur de donnees d'evenements ultra-precis. Ton travail est d'analyser le texte d'un post ou d'une story Instagram et d'en extraire les informations cles pour un evenement a Bali. REGLE ABSOLUE, SANS AUCUNE EXCEPTION : ta reponse complete doit etre UNIQUEMENT l'objet JSON demande, rien d'autre. Jamais de phrase d'introduction, jamais de question, jamais de conclusion, jamais d'explication en dehors du champ "alerte", et jamais de balises markdown. Meme si le texte est vide, ambigu, absent d'information exploitable, ou si tu as le moindre doute : tu reponds quand meme avec l'objet JSON complet ci-dessous, en mettant tes doutes UNIQUEMENT dans le champ "alerte".
Format attendu (toujours ces 3 cles, jamais autre chose) :
{"titre": "Nom de l'event ou du DJ", "date": "YYYY-MM-DD", "alerte": "Message d'alerte si tu as un doute ou si le post ne concerne pas un evenement, sinon vide"}
IMPORTANT SUR LES DATES : les evenements a Bali se produisent dans le present ou le futur proche (annees courantes, y compris 2026 et au-dela) - c'est NORMAL et attendu, ne traite JAMAIS une date recente ou future comme invalide, suspecte ou anormale. Le champ "date" doit TOUJOURS etre soit un format YYYY-MM-DD strictement valide, soit une chaine vide "" si aucune date n'est determinable - ne mets JAMAIS un timestamp brut, un nombre, ou tout autre format dans ce champ, meme si tu as un doute sur la date : mets alors une chaine vide et explique ton doute dans le champ "alerte".
REGLE CRITIQUE - DATE SANS ANNEE PRECISEE (mois+jour seulement, ex: "Sept 19th-21st", "March 5") : n'utilise JAMAIS l'annee courante par defaut de maniere automatique. Utilise TOUJOURS la date de publication du post comme reference pour deduire l'annee correcte : l'evenement a presque toujours lieu PEU DE TEMPS APRES la publication (memes quelques semaines a quelques mois), pas necessairement dans l'annee de aujourd'hui. Si le post a ete publie il y a longtemps (l'annee de publication est differente de l'annee actuelle) et que la date mois+jour mentionnee tombe logiquement dans l'annee DE PUBLICATION (peu apres la publication), utilise cette annee-la, meme si ca rend l'evenement deja passe par rapport a aujourd'hui - dans ce cas, laisse le champ date rempli avec la date reelle passee (le systeme en aval la traitera comme perimee), NE LA DECALE JAMAIS artificiellement vers une annee future juste pour la rendre "a venir".
CAS CALENDRIER MULTI-EVENEMENTS : si le texte decrit plusieurs soirees/evenements differents sur UNE SEMAINE (ex: programme jour par jour), prefixe le titre par "This Week at [nom de la venue]", utilise comme date le premier jour concerne a partir d'aujourd'hui, et detaille le programme complet dans alerte. Si le texte couvre UN MOIS entier, prefixe plutot le titre par "This Month at [nom de la venue]", meme logique pour la date et le detail en alerte."""


def _extract_from_caption(caption: str, published_timestamp: str) -> dict[str, str]:
    user_message = (
        f"Analyse ce texte Instagram (type de contenu : Post) : {caption}\n"
        f"Sache que ce post a ete publie le : {published_timestamp}. Utilise cette date "
        f"de publication pour calculer precisement la date absolue de l'evenement si le "
        f"texte dit 'today', 'tomorrow', 'this Saturday', etc."
    )
    response = claude_client.call_claude(
        POST_EXTRACTION_SYSTEM_PROMPT, user_message, max_tokens=1024
    )
    return claude_client.extract_json_from_response(response)


def _write_event(
    venue_name: str,
    instagram_username: str,
    titre: str,
    date: str,
    alerte: str,
    image_url: str,
    caption_or_raw: str,
    fallback_date_source: str,
) -> None:
    final_date = date if date else fallback_date_source
    airtable_client.create_record(
        settings.AIRTABLE_TABLE_EVENTS,
        {
            settings.FLD_VENUE_NAME: venue_name,
            settings.FLD_STATUT: settings.STATUT_A_VALIDER,
            settings.FLD_IMAGE_URL: image_url,
            settings.FLD_TITRE: titre,
            settings.FLD_ALERTE: alerte,
            settings.FLD_INSTAGRAM: instagram_username,
            settings.FLD_DATE: final_date,
            settings.FLD_LEGENDE: caption_or_raw,
        },
    )


def process_post(account: accounts.Account, post: dict) -> None:
    """Traite un post: dedup -> extraction texte -> fallback vision si besoin -> ecriture."""
    post_url = post.get("url", "")
    if not post_url or dedup.already_processed(post_url):
        return

    caption = post.get("caption", "") or ""
    timestamp = post.get("timestamp", "")
    fallback_date = ""
    if timestamp:
        try:
            fallback_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime(
                "%Y-%m-%d"
            )
        except ValueError:
            pass

    try:
        result = _extract_from_caption(caption, timestamp)
    except claude_client.ClaudeError as exc:
        logger.error("Echec extraction Claude pour post %s: %s", post_url, exc)
        return

    titre = result.get("titre", "")
    date = result.get("date", "")
    alerte = result.get("alerte", "")
    images = post.get("images", []) or []

    if not date and images:
        try:
            vision_result = gemini_client.extract_from_images(images, caption, timestamp)
        except gemini_client.GeminiError as exc:
            logger.error("Echec fallback vision pour post %s: %s", post_url, exc)
            vision_result = {}
        if vision_result:
            titre = vision_result.get("titre") or titre
            date = vision_result.get("date", "")
            alerte = f"[VISION FALLBACK GEMINI] {vision_result.get('alerte', '')}"

    _write_event(
        venue_name=account.venue_name,
        instagram_username=post.get("ownerUsername", ""),
        titre=titre,
        date=date,
        alerte=alerte,
        image_url=post.get("displayUrl", ""),
        caption_or_raw=caption,
        fallback_date_source=fallback_date,
    )
    dedup.mark_processed(post_url)
    logger.info("Post traite: %s (%s)", post_url, "avec date" if date else "sans date")


def process_story(account: accounts.Account, story: dict) -> None:
    """Traite une story: dedup -> vision (toujours, pas de legende fiable) -> ecriture."""
    username = (story.get("user") or {}).get("username", "")
    pk = story.get("pk", "")
    story_url = f"https://www.instagram.com/stories/{username}/{pk}/"

    if not pk or dedup.already_processed(story_url):
        return

    image_candidates = [
        c.get("url") for c in (story.get("image_versions2") or {}).get("candidates", []) if c.get("url")
    ]
    if not image_candidates:
        return

    taken_at = story.get("taken_at")
    fallback_date = ""
    published_timestamp = ""
    if taken_at:
        try:
            dt = datetime.fromtimestamp(int(taken_at))
            fallback_date = dt.strftime("%Y-%m-%d")
            published_timestamp = dt.isoformat()
        except (ValueError, TypeError):
            pass

    try:
        vision_result = gemini_client.extract_from_images(image_candidates[:1], published_timestamp=published_timestamp)
    except gemini_client.GeminiError as exc:
        logger.error("Echec vision pour story %s: %s", story_url, exc)
        return

    # IMPORTANT: toujours utiliser l'image de couverture fixe (image_versions2), jamais l'URL
    # video - GoodBarber rejette les .mp4 comme thumbnail (silencieusement, garde l'ancienne image).
    # Instagram fournit toujours une image de couverture fixe avec le texte du flyer visible,
    # meme pour les stories video - inutile d'extraire une frame de la video nous-memes.
    media_url = image_candidates[0] if image_candidates else ""

    _write_event(
        venue_name=account.venue_name,
        instagram_username=username,
        titre=vision_result.get("titre", ""),
        date=vision_result.get("date", ""),
        alerte=f"[GEMINI VISION] {vision_result.get('alerte', '')}",
        image_url=media_url,
        caption_or_raw="",
        fallback_date_source=fallback_date,
    )
    dedup.mark_processed(story_url)
    logger.info("Story traitee: %s", story_url)


def process_account(account: accounts.Account) -> None:
    """Traite un compte complet: posts puis stories."""
    logger.info("Traitement du compte: %s (%s)", account.venue_name, account.instagram_url)

    posts = apify_client.scrape_posts(account.instagram_url)
    for post in posts:
        process_post(account, post)

    username = account.instagram_url.rstrip("/").split("/")[-1]
    stories = apify_client.scrape_stories(username)
    for story in stories:
        process_story(account, story)
