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
from difflib import SequenceMatcher

from config import settings
from src import airtable_client, claude_client, geocoding, goodbarber_mcp_client, msgraph_client
from src.publication import _report_to_client_and_tracking

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

TIME_SYSTEM_PROMPT = """Extrait l'heure de DEBUT precise mentionnee dans ce texte d'evenement, si elle existe (ex: "doors open at 9pm" -> "21:00", "starts 8pm" -> "20:00", "from 6 to 9pm" -> "18:00"). Si AUCUNE heure precise n'est mentionnee (seulement une date ou un jour), reponds avec une chaine vide. Reponds avec UNIQUEMENT un objet JSON, format : {"time": "HH:MM" ou ""}"""


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


SEO_HASHTAGS = " #seeeventsbali #ifyouseeyouknow"


def _generate_seo_description(titre: str, venue: str) -> str:
    """Petit appel Claude isole (pas d'outils MCP) - uniquement la description SEO.
    Ajoute toujours les hashtags de marque a la fin (regle n°6, oublies dans
    la version initiale de Publication Direct - corrige le 24 aout 2026)."""
    try:
        response = claude_client.call_claude(
            SEO_SYSTEM_PROMPT,
            f"Event: {titre}\nVenue: {venue}, Bali",
            max_tokens=300,
        )
        result = claude_client.extract_json_from_response(response)
        description = result.get("description", "")
    except claude_client.ClaudeError as exc:
        logger.warning("Echec generation SEO pour '%s': %s", titre, exc)
        description = f"Join {titre} at {venue} in Bali - live event, great vibes, don't miss out."
    return description + SEO_HASHTAGS


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


def _extract_event_time(caption: str) -> tuple[int, int] | None:
    """Petit appel Claude isole - extrait une heure precise (heure, minute)
    si mentionnee dans le texte, sinon None (l'event reste allDay)."""
    if not caption:
        return None
    try:
        response = claude_client.call_claude(TIME_SYSTEM_PROMPT, f"Texte: {caption}", max_tokens=50)
        result = claude_client.extract_json_from_response(response)
        time_str = result.get("time", "")
        if not time_str or ":" not in time_str:
            return None
        hour, minute = time_str.split(":")
        return int(hour), int(minute)
    except (claude_client.ClaudeError, ValueError) as exc:
        logger.warning("Echec extraction heure: %s", exc)
        return None


def _extract_category_ids(event: dict) -> list[int]:
    """Extrait les IDs de categories depuis la structure imbriquee 'sections'
    renvoyee par GoodBarber (sections[].categories[].id), pas un simple
    champ 'categories' comme on pourrait le supposer."""
    ids = []
    for section in event.get("sections", []):
        for cat in section.get("categories", []):
            if "id" in cat:
                ids.append(cat["id"])
    return ids


def _title_similarity(a: str, b: str) -> float:
    """Similarite de texte simple (0-1), en Python pur - utilisee pour la
    detection de doublon potentiel (ex: event cree manuellement sans urlEvent)."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


async def _find_existing_event(
    client, venue_name: str, instagram_handle: str, titre: str = "", date_str: str = ""
) -> tuple[dict | None, str]:
    """
    Dedoublonnage en Python pur : cherche un event existant pour cette venue.
    Retourne (candidat_confirme_ou_None, note_doublon_potentiel).
    La note est non-vide si un candidat NON confirme (urlEvent absent/different)
    mais avec un titre tres similaire existe deja a la MEME date - signale
    plutot que fusionne automatiquement (trop risque de melanger deux
    evenements reellement differents), pour que l'equipe verifie manuellement.
    """
    target_username = instagram_handle.lower().rstrip("/")
    unconfirmed_same_date_similar = None

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
                return candidate, ""

            # Pas de correspondance confirmee - verifie si c'est un doublon
            # potentiel (meme date + titre tres similaire, ex: event cree
            # manuellement sans urlEvent renseigne).
            candidate_date = str(candidate.get("sortDate", ""))[:10]
            if titre and date_str and candidate_date == date_str:
                similarity = _title_similarity(titre, candidate.get("title", ""))
                if similarity > 0.5:
                    unconfirmed_same_date_similar = candidate

    if unconfirmed_same_date_similar:
        note = (
            f"DOUBLON POTENTIEL: event existant similaire trouve (id {unconfirmed_same_date_similar['id']}, "
            f"titre '{unconfirmed_same_date_similar.get('title', '')}') a la meme date - verifier manuellement."
        )
        return None, note

    return None, ""


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
    event_time = _extract_event_time(caption)
    full_title = f"{titre} at {venue_name}"
    meta_title = f"{full_title} by SEE Events Bali"

    if event_time:
        hour, minute = event_time
        sort_date_iso = _bali_to_goodbarber_iso(date_str, hour=hour, minute=minute)
        end_date_iso = _bali_to_goodbarber_iso(date_str, hour=23, minute=59)
        all_day = False
    else:
        sort_date_iso = _bali_to_goodbarber_iso(date_str)
        end_date_iso = _bali_to_goodbarber_iso(date_str, hour=23, minute=59)
        all_day = True

    existing_ref, doublon_note = await _find_existing_event(client, venue_name, instagram, titre, date_str)

    if existing_ref:
        event_id = existing_ref["id"]
        # Recupere TOUJOURS le detail complet (sections/categories) via
        # cms_get_event - la recherche cms_list_events peut renvoyer des
        # donnees partielles, on ne veut jamais construire l'update sur
        # des infos incompletes.
        existing = goodbarber_mcp_client.parse_tool_result(
            await client.call_tool("cms_get_event", {"id": event_id})
        )
        current_categories = _extract_category_ids(existing)
        non_date_categories = [c for c in current_categories if c not in (CAT_TODAY, CAT_THIS_WEEK, CAT_LATER)]
        new_categories = list(set(non_date_categories + [date_category, type_category]))
        if CAT_TOP_EVENTS in current_categories and CAT_TOP_EVENTS not in new_categories:
            new_categories.append(CAT_TOP_EVENTS)

        update_args = {
            "id": event_id,
            "title": full_title,
            "categories": new_categories,
            "sortDate": sort_date_iso,
            "endDate": end_date_iso,
            "allDay": all_day,
            "meta": {"title": meta_title[:250], "description": seo_description[:500000]},
            "urlEvent": f"https://www.instagram.com/{instagram}/" if instagram else None,
        }
        update_args = {k: v for k, v in update_args.items() if v is not None}
        await client.call_tool("cms_update_event", update_args)

        paragraphs = goodbarber_mcp_client.parse_tool_result(
            await client.call_tool("cms_list_event_paragraphs", {"id": event_id})
        )
        text_paragraphs = [p for p in paragraphs.get("items", []) if p.get("type") == "text"]
        new_content = f'<span style="color:#FFFFFF">{caption}</span>'

        if text_paragraphs:
            existing_content = text_paragraphs[0].get("content", "")
            if caption and caption not in existing_content:
                # Fusion simple : ajoute le nouveau texte a la suite de l'existant
                # plutot que de l'ecraser (evite de perdre les infos des posts
                # precedents sur le meme evenement - cas des festivals multi-posts).
                merged_content = f'{existing_content}<br/>{new_content}' if existing_content else new_content
            else:
                merged_content = existing_content or new_content
            await client.call_tool(
                "cms_update_event_paragraph",
                {"id": event_id, "paragraph_id": text_paragraphs[0]["id"], "content": merged_content},
            )
        else:
            await client.call_tool(
                "cms_create_event_paragraph", {"id": event_id, "type": "text", "content": new_content}
            )

        # Multi-images : si cette source apporte une nouvelle image (differente
        # du thumbnail principal deja utilise), l'ajoute comme photo
        # supplementaire plutot que de l'ignorer (cas festivals multi-artistes).
        if image_url:
            existing_photos = [p for p in paragraphs.get("items", []) if p.get("type") == "photo"]
            already_present = any(image_url in (p.get("originalThumbnail") or "") for p in existing_photos)
            if not already_present and len(existing_photos) < 8:
                await client.call_tool(
                    "cms_create_event_paragraph",
                    {"id": event_id, "type": "photo", "originalThumbnail": image_url, "isThumbnail": False},
                )

        result = {"status": "UPDATED", "goodbarber_id": event_id, "message": f"Evenement mis a jour (id {event_id})."}
        _report_to_client_and_tracking(record, result["status"], result["message"], event_id)
        return result

    else:
        geo = geocoding.geocode_venue(venue_name)
        create_args = {
            "title": full_title,
            "categories": [date_category, type_category],
            "sortDate": sort_date_iso,
            "endDate": end_date_iso,
            "allDay": all_day,
            "meta": {"title": meta_title[:250], "description": seo_description[:500000]},
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

        base_message = f"Nouvel evenement cree (id {event_id})."
        message = f"{base_message} {doublon_note}".strip() if doublon_note else base_message
        result = {"status": "CREATED", "goodbarber_id": event_id, "message": message}
        _report_to_client_and_tracking(record, result["status"], result["message"], event_id)
        return result


async def _run_all_async(client, records: list[dict]) -> dict[str, int]:
    """Traite tous les enregistrements SEQUENTIELLEMENT dans une seule
    session MCP (evite le cout de reconnexion ~5-10s par enregistrement)."""
    summary: dict[str, int] = {}
    total = len(records)
    for i, record in enumerate(records, start=1):
        record_id = record["id"]
        try:
            result = await publish_one_async(client, record)
            status = result["status"]
            fields = {settings.FLD_ALERTE: result["message"]}
            if status == "ERROR":
                fields[settings.FLD_STATUT] = settings.STATUT_VALIDE
            else:
                fields[settings.FLD_STATUT] = settings.STATUT_RAPPORTE
                fields[settings.FLD_GOODBARBER_ID] = str(result["goodbarber_id"]) if result["goodbarber_id"] else ""
            airtable_client.update_record(settings.AIRTABLE_TABLE_EVENTS, record_id, fields)
            final_status = fields[settings.FLD_STATUT]
        except Exception as exc:
            logger.exception("Echec non-capture pour %s - remis en Valide", record_id)
            airtable_client.update_record(
                settings.AIRTABLE_TABLE_EVENTS,
                record_id,
                {
                    settings.FLD_STATUT: settings.STATUT_VALIDE,
                    settings.FLD_ALERTE: f"ECHEC AUTOMATIQUE (Publication Direct) : {exc}. A traiter manuellement.",
                },
            )
            final_status = settings.STATUT_VALIDE

        summary[final_status] = summary.get(final_status, 0) + 1
        if i % 10 == 0 or i == total:
            logger.info("Progression: %d/%d traitees (%s)", i, total, summary)

    return summary


def run(dry_run_record_ids: list[str] | None = None) -> dict[str, int]:
    """
    Publie toutes les lignes 'Validé' actuelles via le client MCP direct
    (sans agent Claude pour l'orchestration - petits appels Claude isoles
    uniquement pour SEO/categorie/heure). Si `dry_run_record_ids` est
    fourni, ne traite que ces IDs precis (test isole).
    """
    if dry_run_record_ids:
        records = []
        for rid in dry_run_record_ids:
            found = airtable_client.search_records(
                settings.AIRTABLE_TABLE_EVENTS, formula=f"RECORD_ID()='{rid}'", max_records=1
            )
            if found:
                records.append(found[0])
            else:
                logger.warning("ID '%s' introuvable - ignore", rid)
    else:
        records = airtable_client.search_records(
            settings.AIRTABLE_TABLE_EVENTS,
            formula=f"{{Statut}} = '{settings.STATUT_VALIDE}'",
            max_records=settings.MAX_RECORDS_PER_RUN,
        )

    logger.info("Publication Direct: %d ligne(s) a traiter", len(records))
    summary = goodbarber_mcp_client.run_in_session(
        lambda client: _run_all_async(client, records), step_timeout=3600.0
    )
    logger.info("Publication Direct terminee: %s", summary)
    return summary
