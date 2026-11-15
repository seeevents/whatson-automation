"""
Passage hebdomadaire de scrape des happy hours / promos (par venue, par batch).

Chaque venue eligible (memes regles que pour les events : client_type=not_a_client,
frequence, batch 1-8, URL Instagram) est traitee UNE fois par semaine, le jour de son
choix : le jour de scrape de la venue si elle est hebdomadaire, sinon un jour stable
derive de son URL. Chaque passage relit les derniers posts SANS dedoublonnage
Instagram_Items_Vus (une offre deja vue doit pouvoir etre reconfirmee).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from config import settings
from src import apify_client, offers
from src import publication_supabase as ps

logger = logging.getLogger("whatson.offers_scrape")

POSTS_LIMIT = 8          # derniers posts relus par compte
POSTS_NEWER_THAN = "21 days"
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _assigned_weekday(row: dict) -> str:
    days = row.get("scrape_days") or []
    if isinstance(days, str):
        days = [d.strip().lower() for d in days.strip("[]").replace('"', "").split(",") if d.strip()]
    days = [str(d).lower() for d in days if str(d).lower() in _DAYS]
    if (row.get("scrape_frequency") or "").lower() == "once_a_week" and days:
        return days[0]
    h = int(hashlib.sha256((row.get("instagram_url") or "").lower().encode()).hexdigest(), 16)
    return _DAYS[h % 7]


def todays_venues(batch_number: str | None = None, weekday: str | None = None) -> list[dict]:
    weekday = weekday or datetime.now(settings.BALI_TZ).strftime("%A").lower()
    rows = ps._request("GET", "venues", params={
        "select": "name,instagram_url,scrape_frequency,scrape_days,scrape_batch,client_type",
        "client_type": "eq.not_a_client", "limit": "5000"}) or []
    out, seen = [], set()
    for r in rows:
        if (r.get("scrape_frequency") or "").lower() not in ("everyday", "once_a_week"):
            continue
        if str(r.get("scrape_batch") or "") not in tuple("12345678"):
            continue
        if batch_number is not None and str(r["scrape_batch"]) != str(batch_number):
            continue
        url = (r.get("instagram_url") or "").split("?")[0].strip()
        if not url or url in seen or _assigned_weekday(r) != weekday:
            continue
        seen.add(url)
        out.append({"name": r.get("name") or "", "url": url})
    return out


def run(batch_number: str | None = None, write: bool | None = None) -> list[dict]:
    write = settings.OFFERS_WRITE_ENABLED if write is None else write
    today = datetime.now(settings.BALI_TZ).strftime("%Y-%m-%d")
    results: list[dict] = []
    for v in todays_venues(batch_number):
        handle = ps._normalize_handle(v["url"])
        posts = apify_client.scrape_posts(v["url"], limit=POSTS_LIMIT, newer_than=POSTS_NEWER_THAN)
        for post in posts:
            caption = post.get("caption") or ""
            if not offers._prefilter_ok(caption):
                continue
            try:
                res = offers.process_source(caption, v["name"], handle, post.get("displayUrl") or "", today, write)
            except Exception as exc:  # noqa: BLE001
                res = {"action": "error", "note": f"{v['name']}: {type(exc).__name__}: {str(exc)[:200]}"}
            res["venue"] = v["name"]
            results.append(res)
    return results
