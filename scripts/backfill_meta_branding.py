#!/usr/bin/env python3
"""
Correction RETROACTIVE (une seule fois) : ajoute "by SEE Events Bali" au
meta title et les hashtags #seeeventsbali #ifyouseeyouknow a la meta
description, pour les events crees/mis a jour le 24 aout 2026 AVANT le
fix de Publication Direct (qui oubliait ces deux elements).
Ne touche a AUCUN autre champ (titre visible, texte, categories, etc.).
Usage: python scripts/backfill_meta_branding.py id1 id2 id3 ...
"""
import logging
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import goodbarber_mcp_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.backfill_meta_branding")

BRANDING_SUFFIX = " by SEE Events Bali"
HASHTAGS = " #seeeventsbali #ifyouseeyouknow"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:200]


def _dedupe_title(title: str) -> str:
    """Corrige 'X at Venue at Venue2' -> 'X at Venue2' quand les deux
    derniers segments 'at ...' sont tres similaires (pas forcement
    identiques a la lettre pres, ex: 'Legend Bar' vs 'Legends Bar')."""
    parts = re.split(r"\s+at\s+", title, flags=re.IGNORECASE)
    if len(parts) < 3:
        return title
    similarity = SequenceMatcher(None, parts[-1].strip().lower(), parts[-2].strip().lower()).ratio()
    if similarity > 0.75:
        return " at ".join(parts[:-1])
    return title


async def _backfill_one(client, event_id: int) -> str:
    event = goodbarber_mcp_client.parse_tool_result(
        await client.call_tool("cms_get_event", {"id": event_id})
    )
    meta = event.get("meta", {}) or {}
    title = meta.get("title", "") or event.get("title", "")
    description = meta.get("description", "") or ""
    visible_title = event.get("title", "")

    changed = False
    if BRANDING_SUFFIX.strip() not in title:
        title = f"{title}{BRANDING_SUFFIX}"
        changed = True
    if "#seeeventsbali" not in description:
        description = f"{description}{HASHTAGS}"
        changed = True

    update_args = {"id": event_id}
    fixed_visible_title = _dedupe_title(visible_title)
    if fixed_visible_title != visible_title:
        update_args["title"] = fixed_visible_title
        update_args["slug"] = _slugify(fixed_visible_title)
        changed = True
    else:
        # Meme si le titre visible n'a pas change, on resynchronise le slug
        # (corrige les URLs figees sur un tres vieux titre).
        new_slug = _slugify(visible_title)
        update_args["slug"] = new_slug

    if not changed:
        return "deja_correct"

    update_args["meta"] = {"title": title[:250], "description": description[:500000]}
    await client.call_tool("cms_update_event", update_args)
    return "corrige"



async def _backfill_all(client, event_ids: list[int]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for i, event_id in enumerate(event_ids, start=1):
        try:
            result = await _backfill_one(client, event_id)
        except Exception as exc:
            logger.error("Echec pour l'event %s: %s", event_id, exc)
            result = "erreur"
        summary[result] = summary.get(result, 0) + 1
        logger.info("[%d/%d] Event %s: %s", i, len(event_ids), event_id, result)
    return summary


def main() -> int:
    if len(sys.argv) < 2:
        logger.error("Usage: python scripts/backfill_meta_branding.py <id1> [id2...]")
        return 1

    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    event_ids = [int(x) for x in sys.argv[1:]]
    logger.warning("Correction retroactive de %d event(s): %s", len(event_ids), event_ids)

    summary = goodbarber_mcp_client.run_in_session(
        lambda client: _backfill_all(client, event_ids), step_timeout=1800.0
    )
    logger.info("Résumé final: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
