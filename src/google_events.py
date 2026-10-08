"""
Filet de securite hebdomadaire : events Google (concerts, boat parties, shows,
festivals...) pour Bali. Complete le scraping Instagram, qui rate certains
posts (restriction d'age, posts epingles anciens). Les events trouves sont
ecrits dans Events_Collectes (statut "A valider"), puis passent par le Tri
normal. Instagram handle laisse VIDE volontairement : pas de faux lien
instagram.com dans l'app.
"""
from __future__ import annotations

import logging
import re

from config import settings
from src import airtable_client, apify_client, dedup

logger = logging.getLogger("whatson.google_events")

ACTOR = "omkar-cloud/google-events-scraper"
QUERIES = [
    "events in Canggu Bali",
    "events in Seminyak Bali",
    "events in Uluwatu Bali",
    "events in Ubud Bali",
    "events in Sanur Bali",
    "live music Bali",
    "party DJ Bali",
    "festival Bali",
]
MAX_RESULTS = 120

# Bruit connu (retour du test du 8 oct 2026) : bien-etre, cours, ateliers.
NOISE_PATTERN = re.compile(
    r"\b(yoga|meditation|sound\s?(bath|healing)|reiki|retreat|breathwork|cacao|pilates|"
    r"workshop|class|course|training|pottery|ceramic|healing|wellness|holistic|"
    r"seminar|webinar|conference|networking)\b",
    re.IGNORECASE,
)


def _is_noise(item: dict) -> bool:
    text = f"{item.get('title') or ''} {item.get('type') or ''}"
    return bool(NOISE_PATTERN.search(text))


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _existing_keys(dates: set[str]) -> set[tuple[str, str]]:
    """(date, venue normalisee) deja presents dans Events_Collectes pour ces dates."""
    keys: set[tuple[str, str]] = set()
    for d in dates:
        recs = airtable_client.search_records(
            settings.AIRTABLE_TABLE_EVENTS,
            formula=f"IS_SAME({{{settings.FLD_DATE}}}, '{d}', 'day')",
            fields=[settings.FLD_VENUE_NAME, settings.FLD_DATE],
            max_records=500,
        )
        for r in recs:
            f = r.get("fields", {})
            keys.add((d, _normalize(f.get(settings.FLD_VENUE_NAME, ""))))
    return keys


def run() -> dict[str, int]:
    items = apify_client._run_sync_get_dataset_items(
        ACTOR,
        {
            "queries": QUERIES,
            "date": "this_week",
            "country": "US",
            "language": "en",
            "maxResults": MAX_RESULTS,
        },
        timeout=600,
    )
    stats = {"fetched": len(items), "noise": 0, "dup_run": 0, "dup_existing": 0, "created": 0}

    seen_ids: set[str] = set()
    candidates = []
    for it in items:
        uid = str(it.get("id") or it.get("link") or it.get("title"))
        if uid in seen_ids:
            stats["dup_run"] += 1
            continue
        seen_ids.add(uid)
        if _is_noise(it):
            stats["noise"] += 1
            continue
        candidates.append((uid, it))

    dates = {(it.get("schedule") or {}).get("start_date", "") for _, it in candidates} - {""}
    existing = _existing_keys(dates)

    for uid, it in candidates:
        sched = it.get("schedule") or {}
        venue = it.get("venue") or {}
        date = sched.get("start_date", "")
        venue_name = venue.get("name", "")
        dedup_key = f"google-event:{uid}"
        if not date or dedup.already_processed(dedup_key):
            stats["dup_existing"] += 1
            continue
        if (date, _normalize(venue_name)) in existing:
            stats["dup_existing"] += 1
            dedup.mark_processed(dedup_key)
            continue

        time_str = sched.get("start_time", "")
        legende = (
            f"{it.get('title', '')}\n"
            f"Type: {it.get('type') or ''}\n"
            f"Date: {date} {time_str}\n"
            f"Venue: {venue_name} ({venue.get('locality', '')})\n"
            f"Source: Google Events {it.get('link', '')}"
        )
        airtable_client.create_record(
            settings.AIRTABLE_TABLE_EVENTS,
            {
                settings.FLD_VENUE_NAME: venue_name,
                settings.FLD_STATUT: settings.STATUT_A_VALIDER,
                settings.FLD_IMAGE_URL: it.get("thumbnail", "") or "",
                settings.FLD_TITRE: it.get("title", ""),
                settings.FLD_ALERTE: "[GOOGLE EVENTS] filet hebdo - verifier venue/adresse",
                settings.FLD_DATE: date,
                settings.FLD_LEGENDE: legende,
            },
        )
        dedup.mark_processed(dedup_key)
        stats["created"] += 1

    logger.info("Google Events: %s", stats)
    return stats
