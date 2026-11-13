"""
Happy hours et promos recurrentes -> table Supabase `venue_offers` (V2).

Source : lignes Airtable `Events_Collectes` que le Tri a mises en "Ignoré"
(les pseudo-evenements recurrents), relues sur une fenetre de quelques jours.
Mode ESSAI A BLANC par defaut : rien n'est ecrit tant que
OFFERS_WRITE_ENABLED n'est pas "true".

Regles (spec du back-office) :
- kind = 'happy_hour' ou 'promo' uniquement ; slug / seo_* laisses VIDES (le BO les genere).
- Venue principale uniquement (linked_venue_id vide, non masquee).
- Cle de doublon : meme venue + kind + jours + heure de debut -> mise a jour.
- is_active = true seulement si jours ET heures connus ; sinon false (rien deviner).
- Ne jamais ecraser une offre modifiee a la main (updated_at plus recent que
  notre derniere ecriture, approximee par last_verified_at) : on ne touche
  alors qu'a last_verified_at.
- Offre disparue : is_active=false, jamais de suppression (non gere ici : necessite
  de savoir qu'un compte a ete scrape sans la reconfirmer ; a ajouter plus tard).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from config import settings
from src import airtable_client, claude_client, dedup
from src import publication_supabase as ps

logger = logging.getLogger("whatson.offers")

LOOKBACK_DAYS = 2
MANUAL_EDIT_GRACE = timedelta(hours=2)  # le BO ecrit slug/SEO/market apres creation
_seen_run: list[tuple[str, str, str]] = []

PREFILTER = re.compile(
    r"happy\s*hours?|ladies?\s*night|free\s*flow|\b\d\s*(for|x)\s*\d\b|buy\s*\d.*get\s*\d|"
    r"\d{1,2}\s*%\s*off|discount|promo|special\s+(offer|price|deal)|drinks?\s+special|"
    r"all[-\s]you[-\s]can|unlimited|brunch|ladies\s+drink|bogo",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """Tu analyses un post Instagram d'un bar/restaurant/club de Bali pour en extraire une OFFRE RECURRENTE (happy hour ou promo).
Reponds UNIQUEMENT avec un objet JSON :
{"is_offer": bool, "kind": "happy_hour"|"promo", "title": str, "description": str|null,
 "days_of_week": [int]|null, "start_time": "HH:MM"|null, "end_time": "HH:MM"|null,
 "start_date": "YYYY-MM-DD"|null, "end_date": "YYYY-MM-DD"|null, "reason": str}
Regles :
- is_offer=true seulement pour une offre commerciale recurrente ou durable (happy hour, ladies night, brunch avec formule, 2 pour 1, free flow, promo sur la carte avec prix/remise). false pour un evenement ponctuel avec DJ/line-up/date precise (c'est un event), un simple plat sans offre, un post sans offre.
- kind="happy_hour" pour une happy hour ; tout le reste (ladies night, brunch, offre boissons, offre du jour) = "promo".
- title : court, en anglais, avec le detail (ex: "Happy Hour: 2 for 1 cocktails", "Ladies Night: free flow 200k").
- description : l'offre en une phrase (prix, remise, conditions), sinon null.
- days_of_week : entiers ISO, 1=lundi ... 7=dimanche ("daily"/"every day" = [1,2,3,4,5,6,7], "Mon-Fri" = [1,2,3,4,5]). null si le post ne le dit pas.
- start_time / end_time : heure de Bali au format 24h. Si une seule borne est donnee, l'autre est null. NE JAMAIS DEVINER : si absent, null.
- start_date / end_date : seulement si le post donne explicitement une date de debut / de fin (ex: "from 15 Nov", "until 30 Nov", "all month long" = fin du mois courant), sinon null.
"""


def _prefilter_ok(caption: str) -> bool:
    return bool(caption and PREFILTER.search(caption))


def _hhmm(value) -> str | None:
    if not value:
        return None
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*", str(value))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}:00"


def extract_offer(caption: str, venue_name: str, today: str) -> dict | None:
    """Appel Claude ; retourne un dict normalise ou None si ce n'est pas une offre."""
    user = f"Date du jour (Bali) : {today}\nLieu : {venue_name}\n\nLegende du post :\n{caption[:3000]}"
    data = None
    for max_tokens in (1000, 2000):  # 2e essai plus large si la reponse est tronquee
        try:
            data = claude_client.extract_json_from_response(
                claude_client.call_claude(SYSTEM_PROMPT, user, max_tokens=max_tokens))
            break
        except claude_client.ClaudeError:
            if max_tokens == 2000:
                raise
    
    if not data.get("is_offer"):
        return None
    kind = data.get("kind") if data.get("kind") in ("happy_hour", "promo") else "promo"
    title = (data.get("title") or "").strip()[:120]
    if not title:
        return None
    days = data.get("days_of_week")
    days = sorted({int(d) for d in days if str(d).isdigit() and 1 <= int(d) <= 7}) if isinstance(days, list) else []
    def _iso(v):
        return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v or "")) else None
    end_date = _iso(data.get("end_date"))
    start_date = _iso(data.get("start_date"))
    if end_date and end_date < today:  # offre deja terminee
        return None
    return {
        "kind": kind,
        "title": title,
        "description": (data.get("description") or "").strip() or None,
        "days_of_week": days,
        "start_time": _hhmm(data.get("start_time")),
        "end_time": _hhmm(data.get("end_time")),
        "start_date": start_date,
        "end_date": end_date,
        "explicit_end": bool(end_date),
    }


def _month_end(today: str) -> str:
    d = datetime.strptime(today, "%Y-%m-%d")
    nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (nxt - timedelta(days=1)).strftime("%Y-%m-%d")


def _edited_by_hand(existing: dict) -> bool:
    """updated_at depasse last_verified_at de plus de 2 h (le BO ecrit slug/SEO/market juste apres la creation)."""
    try:
        upd = datetime.fromisoformat(str(existing["updated_at"]).replace("Z", "+00:00"))
        ver = datetime.fromisoformat(str(existing["last_verified_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError):
        return False
    return upd - ver > MANUAL_EDIT_GRACE


def _marker(id_offer: str, end_date: str) -> str:
    return f"offer-end-default:{id_offer}:{end_date}"


def _mark_default_end(id_offer: str, end_date: str) -> None:
    """Memorise (table Instagram_Items_Vus) que NOUS avons pose cette fin par defaut."""
    try:
        dedup.mark_processed(_marker(id_offer, end_date))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Marqueur fin par defaut non enregistre (%s)", type(exc).__name__)


def _end_is_default(id_offer: str, end_date: str) -> bool:
    try:
        return dedup.already_processed(_marker(id_offer, end_date))
    except Exception:  # noqa: BLE001
        return False  # dans le doute on ne prolonge pas


def _venue_is_main(id_venue: str) -> tuple[bool, str, dict]:
    rows = ps._request("GET", "venues", params={
        "select": "id_venue,market,is_hidden,linked_venue_id", "id_venue": f"eq.{id_venue}", "limit": "1"}) or []
    if not rows:
        return False, "venue introuvable", {}
    v = rows[0]
    if v.get("is_hidden"):
        return False, "venue masquee", v
    if v.get("linked_venue_id"):
        return False, "venue liee (ecrire sur la venue principale)", v
    return True, "", v


def _titles_close(a: str, b: str) -> bool:
    na, nb = ps._normalize_text(a), ps._normalize_text(b)
    if not na or not nb:
        return False
    return na in nb or nb in na or ps._similarity(a, b) >= 0.6


def _find_existing(id_venue: str, offer: dict) -> dict | None:
    rows = ps._request("GET", "venue_offers", params={
        "select": "*", "id_venue": f"eq.{id_venue}", "kind": f"eq.{offer['kind']}", "limit": "50"}) or []
    for r in rows:
        if (sorted(r.get("days_of_week") or []) == offer["days_of_week"]
                and offer["start_time"] and (r.get("start_time") or "") == offer["start_time"]):
            return r
    # Heure de debut inconnue : meme venue + meme kind + memes jours (si connus des deux
    # cotes) + titre proche (similarite >= 0.6 ou l'un contient l'autre).
    if True:
        for r in rows:
            r_days = sorted(r.get("days_of_week") or [])
            if offer["days_of_week"] and r_days and r_days != offer["days_of_week"]:
                continue
            if _titles_close(offer["title"], r.get("title") or ""):
                return r
    return None


def _same_day_key_missing(offer: dict) -> bool:
    """Sans jours/heure de debut, pas de cle de doublon fiable."""
    return not (offer["days_of_week"] and offer["start_time"])


def build_row(offer: dict, venue: dict, image_url: str, today: str) -> dict:
    active = bool(offer["days_of_week"] and offer["start_time"] and offer["end_time"])
    return {
        "id_venue": venue["id_venue"],
        "kind": offer["kind"],
        "title": offer["title"],
        "description": offer["description"],
        "image_url": image_url or None,
        "days_of_week": offer["days_of_week"] or None,
        "start_time": offer["start_time"],
        "end_time": offer["end_time"],
        # Dates : celles du post si elles existent ; sinon debut = jour du scrape,
        # fin = fin du mois en cours (regle validee avec Katia).
        "start_date": offer.get("start_date") or today,
        "end_date": offer["end_date"] or _month_end(today),
        "is_active": active,
        "market": venue.get("market"),
    }


def process_record(record: dict, today: str, write: bool) -> dict:
    """Traite une ligne Airtable. Retourne {'action', 'note', 'offer'}."""
    f = record["fields"]
    caption = f.get(settings.FLD_LEGENDE, "") or ""
    venue_name = f.get(settings.FLD_VENUE_NAME, "") or ""
    handle = ps._normalize_handle(f.get(settings.FLD_INSTAGRAM, "") or "")
    image_url = f.get(settings.FLD_IMAGE_URL, "") or ""

    if not _prefilter_ok(caption):
        return {"action": "skip", "note": "aucun mot-cle d'offre"}
    offer = extract_offer(caption, venue_name, today)
    if not offer:
        return {"action": "skip", "note": "pas une offre recurrente"}

    venue, reason = ps._find_venue(handle, venue_name)
    if not venue:
        return {"action": "skip_venue", "note": f"venue {reason} pour '{venue_name}' (@{handle})", "offer": offer}
    ok, why, vfull = _venue_is_main(venue["id_venue"])
    if not ok:
        return {"action": "skip_venue", "note": why, "offer": offer}
    venue = {**venue, **vfull}

    row = build_row(offer, venue, image_url, today)
    existing = _find_existing(venue["id_venue"], offer)
    for sid, skind, stitle in _seen_run:  # meme offre deja vue dans ce passage (posts repetes)
        if (sid == venue["id_venue"] and skind == offer["kind"]
                and ps._similarity(offer["title"], stitle) >= 0.7):
            return {"action": "skip_duplicate", "note": f"{venue_name}: meme offre deja vue dans ce passage"}
    _seen_run.append((venue["id_venue"], offer["kind"], offer["title"]))
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        # Modifiee a la main depuis notre derniere ecriture ? -> seulement last_verified_at.
        manual = _edited_by_hand(existing)
        patch = {"last_verified_at": now}
        if not manual and settings.OFFERS_UPDATE_MODE == "full":
            cur_end = existing.get("end_date")
            if offer["explicit_end"]:
                patch["end_date"] = offer["end_date"]          # dates du post : telles quelles
            elif cur_end and cur_end < row["end_date"] and _end_is_default(existing["id_offer"], cur_end):
                patch["end_date"] = row["end_date"]            # prolongation: fin posee par defaut par nous
            # champs vides seulement (jamais d'ecrasement)
            for k in ("description", "end_time", "image_url"):
                if row.get(k) and not existing.get(k):
                    patch[k] = row[k]
        if write:
            ps._request("PATCH", "venue_offers", params={"id_offer": f"eq.{existing['id_offer']}"},
                        json_body=patch, prefer="return=minimal")
            if "end_date" in patch and not offer["explicit_end"]:
                _mark_default_end(existing["id_offer"], patch["end_date"])
        return {"action": "update_verified_only" if manual else "update", "note": venue_name, "offer": row,
                "id": existing["id_offer"]}

    row.update({"id_offer": str(uuid.uuid4()), "last_verified_at": now})
    if write:
        ps._request("POST", "venue_offers", json_body=row, prefer="return=minimal")
        if not offer["explicit_end"]:
            _mark_default_end(row["id_offer"], row["end_date"])
    return {"action": "create", "note": venue_name, "offer": row}


def run(write: bool | None = None, lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    write = settings.OFFERS_WRITE_ENABLED if write is None else write
    today = datetime.now(settings.BALI_TZ).strftime("%Y-%m-%d")
    formula = (f"AND({{Statut}} = '{settings.STATUT_IGNORE}', "
               f"IS_AFTER(CREATED_TIME(), DATEADD(NOW(), -{int(lookback_days)}, 'days')))")
    records = airtable_client.search_records(settings.AIRTABLE_TABLE_EVENTS, formula=formula, max_records=2000)
    results = []
    _seen_run.clear()
    for rec in records:
        try:
            res = process_record(rec, today, write)
        except Exception as exc:  # noqa: BLE001
            res = {"action": "error", "note": f"{type(exc).__name__}: {str(exc)[:150]}"}
        res["record_id"] = rec["id"]
        results.append(res)
    return results
