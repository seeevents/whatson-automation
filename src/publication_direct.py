"""
Module de Publication DIRECT - logique metier (dedoublonnage, decision
creation/mise a jour, ecriture) en Python pur via le client MCP direct
(src/goodbarber_mcp_client.py), sans passer par l'agent Claude pour
l'orchestration. Ne garde des petits appels Claude ISOLES (pas d'outils
MCP attaches, donc peu couteux) que pour les taches necessitant une vraie
comprehension du langage : description SEO, categorie de type (DJ/Food/
etc), et synthese multi-sources.

Objectif explicite (demande utilisateur) : minimiser au maximum les
credits Anthropic, dans une logique de sobriete/ecologie autant que de
cout, tout en preservant la qualite des decisions difficiles.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from config import settings
from src import airtable_client, claude_client, geocoding, goodbarber_mcp_client, msgraph_client

logger = logging.getLogger("whatson.publication_direct")

# --- Categories fixes GoodBarber (confirmees stables) ---
CAT_TODAY = 10679997
CAT_THIS_WEEK = 10679998
CAT_LATER = 10680000
CAT_TOP_EVENTS = 10683231  # jamais toucher
CAT_TYPES = {
    "DJ": 16725017,
    "Food": 10680003,
    "Kids": 10680004,
    "Art": 10680005,
    "Sport": 10680006,
    "Dance": 10680007,
    "Wellness": 10680008,
    "Other": 10680009,
}

SEO_SYSTEM_PROMPT = """Write a SEO meta description for the given event in the given venue in Bali in approximately 120 characters in english and using SEO longtail keywords. Respond with ONLY a JSON object, nothing else, format: {"description": "..."}"""

CATEGORY_SYSTEM_PROMPT = """Tu classes un evenement dans UNE categorie de type parmi : DJ, Food, Kids, Art, Sport, Dance, Wellness, Other. Choisis DJ si un DJ ou artiste musical live est mentionne. Choisis Other si aucune categorie ne correspond clairement. Reponds avec UNIQUEMENT un objet JSON, format : {"category": "DJ|Food|Kids|Art|Sport|Dance|Wellness|Other"}"""


def _extract_instagram_username(url: str) -> str:
    """Extrait le nom d'utilisateur Instagram d'une URL, normalise (casse, slash final)."""
    if not url:
        return ""
    match = re.search(r"instagram\.com/([^/?]+)", url, re.IGNORECASE)
    return match.group(1).lower().rstrip("/") if match else ""


def _compute_date_category(event_date_str: str) -> int:
    """Reproduit la formule de categorie de date (Today/This Week/Later)."""
    if not event_date_str:
        return CAT_LATER
    try:
        event_date = datetime.strptime(str(event_date_str)[:10], "%Y-%m-%d").date()
    except ValueError:
        return CAT_LATER
    today = datetime.now(settings.BALI_TZ).date()
    if event_date == today:
        return CAT_TODAY
    days_until_sunday = 7 - today.isoweekday()
    end_of_week = today + timedelta(days=days_until_sunday)
    if event_date <= end_of_week:
        return CAT_THIS_WEEK
    return CAT_LATER


def _bali_to_goodbarber_iso(date_str: str, hour: int = 20, minute: int = 0) -> str:
    """
    Convertit une date (YYYY-MM-DD) + heure Bali en chaine ISO avec le
    fuseau GoodBarber (UTC+2, Bali = UTC+8 -> soustraire 6h). Par defaut
    20h Bali si aucune heure precise n'est connue (allDay gere separement).
    """
    dt_bali = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute)
    dt_goodbarber = dt_bali - timedelta(hours=6)
    return dt_goodbarber.strftime("%Y-%m-%dT%H:%M:%S+02:00")


def _generate_seo_description(titre: str, venue: str) -> str:
    """Petit appel Claude isole (pas d'outils MCP) - uniquement la description SEO."""
    try:
        response = claude_client.call_claude(
            SEO_SYSTEM_PROMPT,
            f"Event: {titre}\nVenue: {venue}, Bali",
            max_tokens=200,
        )
        result = claude_client.extract_json_from_response(response)
        return result.get("description", "")
    except claude_client.ClaudeError as exc:
        logger.warning("Echec generation SEO pour '%s': %s", titre, exc)
        return f"Join {titre} at {venue} in Bali - live event, great vibes, don't miss out."


def _classify_type_category(titre: str, caption: str) -> int:
    """Petit appel Claude isole (pas d'outils MCP) - uniquement la categorie de type."""
    try:
        response = claude_client.call_claude(
            CATEGORY_SYSTEM_PROMPT,
            f"Titre: {titre}\nTexte: {caption}",
            max_tokens=100,
        )
        result = claude_client.extract_json_from_response(response)
        category_name = result.get("category", "Other")
        return CAT_TYPES.get(category_name, CAT_TYPES["Other"])
    except claude_client.ClaudeError as exc:
        logger.warning("Echec classification categorie pour '%s': %s", titre, exc)
        return CAT_TYPES["Other"]


async def _find_existing_event(client, venue_name: str, instagram_handle: str) -> dict | None:
    """Dedoublonnage en Python pur : cherche un event existant pour cette venue."""
    target_username = instagram_handle.lower().rstrip("/")

    for search_term in (venue_name, instagram_handle):
        if not search_term:
            continue
        result = goodbarber_mcp_client.parse_tool_result(
            await client.call_tool("cms_list_events", {"search": [search_term], "per_page": 20})
        )
        candidates = result.get("items", result.get("events", []))
        for candidate in candidates[:5]:  # plafond, evite trop d'appels get_event
            url_event = candidate.get("urlEvent", "")
            if not url_event:
                detail = goodbarber_mcp_client.parse_tool_result(
                    await client.call_tool("cms_get_event", {"id": candidate["id"]})
                )
                url_event = detail.get("urlEvent", "")
            if _extract_instagram_username(url_event) == target_username:
                return candidate
    return None


async def publish_one_async(client, record: dict) -> dict:
    """
    Publie une ligne Airtable sur GoodBarber, en Python pur (dedoublonnage,
    decision creation/mise a jour, ecriture), avec petits appels Claude
    isoles uniquement pour SEO et categorie de type.
    Retourne {"status": "CREATED"|"UPDATED"|"ERROR", "goodbarber_id": int|None, "message": str}
    """
    f = record["fields"]
    venue_name = f.get(settings.FLD_VENUE_NAME, "")
    instagram = f.get(settings.FLD_INSTAGRAM, "")
    titre = f.get(settings.FLD_TITRE, "")
    date_str = f.get(settings.FLD_DATE, "")
    caption = f.get(settings.FLD_LEGENDE, "")
    image_url = f.get(settings.FLD_IMAGE_URL, "")

    if not date_str:
        return {"status": "ERROR", "goodbarber_id": None, "message": "Aucune date - impossible de publier."}

    date_category = _compute_date_category(date_str)
    type_category = _classify_type_category(titre, caption)
    seo_description = _generate_seo_description(titre, venue_name)
    full_title = f"{titre} at {venue_name}"

    existing = await _find_existing_event(client, venue_name, instagram)

    if existing:
        event_id = existing["id"]
        current_categories = existing.get("categories", [])
        non_date_categories = [c for c in current_categories if c not in (CAT_TODAY, CAT_THIS_WEEK, CAT_LATER)]
        new_categories = list(set(non_date_categories + [date_category]))
        if CAT_TOP_EVENTS in current_categories and CAT_TOP_EVENTS not in new_categories:
            new_categories.append(CAT_TOP_EVENTS)

        update_args = {
            "id": event_id,
            "title": full_title,
            "categories": new_categories,
            "sortDate": _bali_to_goodbarber_iso(date_str),
            "endDate": _bali_to_goodbarber_iso(date_str, hour=23, minute=59),
            "allDay": True,
            "meta": {"title": full_title[:250], "description": seo_description[:500000]},
            "urlEvent": f"https://www.instagram.com/{instagram}/" if instagram else None,
        }
        update_args = {k: v for k, v in update_args.items() if v is not None}
        await client.call_tool("cms_update_event", update_args)

        paragraphs = goodbarber_mcp_client.parse_tool_result(
            await client.call_tool("cms_list_event_paragraphs", {"id": event_id})
        )
        text_paragraphs = [p for p in paragraphs.get("items", []) if p.get("type") == "text"]
        content_html = f'<span style="color:#FFFFFF">{caption}</span>'
        if text_paragraphs:
            await client.call_tool(
                "cms_update_event_paragraph",
                {"id": event_id, "paragraph_id": text_paragraphs[0]["id"], "content": content_html},
            )
        else:
            await client.call_tool(
                "cms_create_event_paragraph", {"id": event_id, "type": "text", "content": content_html}
            )

        return {"status": "UPDATED", "goodbarber_id": event_id, "message": f"Evenement mis a jour (id {event_id})."}

    else:
        geo = geocoding.geocode_venue(venue_name)
        create_args = {
            "title": full_title,
            "categories": [date_category, type_category],
            "sortDate": _bali_to_goodbarber_iso(date_str),
            "endDate": _bali_to_goodbarber_iso(date_str, hour=23, minute=59),
            "allDay": True,
            "meta": {"title": full_title[:250], "description": seo_description[:500000]},
            "urlEvent": f"https://www.instagram.com/{instagram}/" if instagram else None,
        }
        if geo:
            create_args["address"] = geo["address"]
            create_args["latitude"] = geo["latitude"]
            create_args["longitude"] = geo["longitude"]
        create_args = {k: v for k, v in create_args.items() if v is not None}

        created = goodbarber_mcp_client.parse_tool_result(
            await client.call_tool("cms_create_event", create_args)
        )
        event_id = created.get("id")

        content_html = f'<span style="color:#FFFFFF">{caption}</span>'
        await client.call_tool("cms_create_event_paragraph", {"id": event_id, "type": "text", "content": content_html})
        if image_url:
            await client.call_tool(
                "cms_create_event_paragraph",
                {"id": event_id, "type": "photo", "originalThumbnail": image_url, "isThumbnail": True},
            )

        return {"status": "CREATED", "goodbarber_id": event_id, "message": f"Nouvel evenement cree (id {event_id})."}
