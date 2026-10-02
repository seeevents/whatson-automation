"""
Publication V2 (Supabase) - duplique sur la V2 ce que publication_direct
vient de publier sur GoodBarber (V1), tant que tous les utilisateurs ne sont
pas passes sur la V2.

Regles :
- GoodBarber reste PRIORITAIRE : ce module ne leve jamais d'exception
  (publish_to_supabase absorbe tout et renvoie un statut). Une panne
  Supabase ne doit jamais bloquer ni casser la publication GoodBarber.
- Aucun secret en dur : SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY viennent
  des secrets GitHub Actions (jamais loggues).
- Venue introuvable cote Supabase -> on ne publie PAS sur la V2 pour cette
  ligne et on renvoie "skipped_no_venue" (l'equipe cree la venue dans le
  back-office). On ne cree jamais de fiche venue automatiquement.
- Un event cree a la main par l'equipe (source_type != "scraped") n'est
  JAMAIS modifie par le pipeline.

Acces : API REST Supabase (PostgREST) via `requests`, avec la cle secrete
(qui contourne le RLS) - meme cle utilisable plus tard pour Supabase Storage.

Images : l'image Instagram (URL qui expire en quelques jours) est telechargee
et rangee dans le bucket PUBLIC "event-images" de Supabase Storage ; c'est
l'URL permanente qui est enregistree dans events.image_url. Si le reheberge
echoue (bucket absent, image trop lourde...), on garde l'URL brute et le
message V2 le signale ("image non rehebergee") - la publication continue.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import requests

from config import settings

logger = logging.getLogger("whatson.publication_supabase")

TIMEOUT = 20
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2

# Reheberge des images (Supabase Storage) : bucket PUBLIC a creer cote Supabase.
IMAGE_BUCKET = "event-images"
IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
IMAGE_USER_AGENT = "Mozilla/5.0 (compatible; SEEEventsBot/1.0)"

DEFAULT_HOUR_BALI = 20          # meme defaut que GoodBarber quand aucune heure n'est connue
DATE_WINDOW_DAYS = 2            # meme fenetre que la fusion GoodBarber (+/- 2 jours)
TITLE_SIMILARITY_MIN = 0.6      # titre "proche" pour considerer que c'est le meme event
VENUE_NAME_SIMILARITY_MIN = 0.85
VENUE_NAME_MARGIN = 0.05        # ecart minimum entre le meilleur et le 2e candidat (sinon ambigu)

VENUE_COLUMNS = "id_venue,name,instagram_url,market,latitude,longitude"
EVENT_COLUMNS = "id_event,title,date_time,end_date_time,description,image_url,source_type"

_not_configured_logged = False


class SupabaseError(Exception):
    """Erreur lors d'un appel a l'API Supabase (le message ne contient jamais la cle)."""


# --------------------------------------------------------------------------
# Acces HTTP
# --------------------------------------------------------------------------

def _is_configured() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    headers = {"apikey": key, "Content-Type": "application/json"}
    # Les nouvelles cles (sb_secret_...) ne sont pas des JWT : elles ne se
    # transmettent que dans "apikey". Les anciennes cles service_role (JWT)
    # se transmettent aussi dans Authorization.
    if not key.startswith("sb_"):
        headers["Authorization"] = f"Bearer {key}"
    if extra:
        headers.update(extra)
    return headers


def _request(method: str, table: str, *, params=None, json_body=None, prefer: str | None = None):
    url = f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/{table}"
    headers = _headers({"Prefer": prefer} if prefer else None)
    last_error = "inconnue"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(
                method, url, headers=headers, params=params, json=json_body, timeout=TIMEOUT
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = f"{type(exc).__name__}"
        else:
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = f"HTTP {resp.status_code}"
            elif not resp.ok:
                # Erreur "definitive" (schema, contrainte, droits) : inutile de reessayer.
                raise SupabaseError(f"{method} {table} -> HTTP {resp.status_code}: {resp.text[:500]}")
            else:
                return resp.json() if resp.content else None
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise SupabaseError(f"{method} {table} -> echec apres {MAX_RETRIES} tentatives ({last_error})")


# --------------------------------------------------------------------------
# Normalisation / dates
# --------------------------------------------------------------------------

def _normalize_handle(value: str) -> str:
    """Accepte un handle ('@nom', 'nom') ou une URL Instagram, renvoie 'nom' en minuscules."""
    if not value:
        return ""
    value = value.strip()
    match = re.search(r"instagram\.com/([^/?#\s]+)", value, re.IGNORECASE)
    handle = match.group(1) if match else value
    return handle.lstrip("@").strip("/").lower()


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _similarity(a: str, b: str) -> float:
    a, b = _normalize_text(a), _normalize_text(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _bali_to_utc(date_str: str, hour: int, minute: int) -> datetime:
    """Date YYYY-MM-DD + heure de Bali (WITA, UTC+8, sans heure d'ete) -> datetime UTC."""
    local = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").replace(
        hour=hour, minute=minute, tzinfo=settings.BALI_TZ
    )
    return local.astimezone(timezone.utc)


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


# --------------------------------------------------------------------------
# Reheberge des images (Supabase Storage)
# --------------------------------------------------------------------------

def _image_target(image_url: str) -> tuple[str, str]:
    """
    (chemin dans le bucket, URL publique permanente) pour une image source.
    Le chemin ne depend que de l'URL SANS ses parametres (les parametres
    Instagram changent, le fichier non) : la meme image donne toujours le
    meme fichier, donc un re-run n'en cree jamais un second.
    """
    stable = image_url.split("?", 1)[0]
    ext_match = re.search(r"\.(jpg|jpeg|png|webp|gif)$", stable, re.IGNORECASE)
    ext = ext_match.group(1).lower() if ext_match else "jpg"
    path = f"{hashlib.sha256(stable.encode()).hexdigest()[:40]}.{ext}"
    public_url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{IMAGE_BUCKET}/{path}"
    return path, public_url


def _rehost_image(image_url: str) -> tuple[str, str]:
    """
    Telecharge l'image Instagram et la range dans Supabase Storage.
    Retourne (url_a_enregistrer, note). Succes : (URL publique permanente, "").
    Echec (best-effort, ne leve jamais) : (URL brute d'origine, raison courte)
    - l'URL brute expirera en quelques jours, la note previent l'equipe.
    """
    path, public_url = _image_target(image_url)
    try:
        resp = requests.get(
            image_url, timeout=TIMEOUT, stream=True, headers={"User-Agent": IMAGE_USER_AGENT}
        )
        if not resp.ok:
            return image_url, f"image non rehebergee (telechargement HTTP {resp.status_code})"
        content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type not in IMAGE_CONTENT_TYPES:
            return image_url, f"image non rehebergee (type {content_type or 'inconnu'} non supporte)"
        data = bytearray()
        for chunk in resp.iter_content(64 * 1024):
            data.extend(chunk)
            if len(data) > IMAGE_MAX_BYTES:
                return image_url, "image non rehebergee (fichier trop volumineux)"
        resp.close()

        upload = requests.request(
            "POST",
            f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/{IMAGE_BUCKET}/{path}",
            headers=_headers({"Content-Type": content_type, "x-upsert": "true",
                              "Cache-Control": "max-age=31536000"}),
            data=bytes(data),
            timeout=TIMEOUT,
        )
        if not upload.ok:
            return image_url, f"image non rehebergee (stockage refuse HTTP {upload.status_code}: {upload.text[:150]})"
        return public_url, ""
    except requests.RequestException as exc:
        return image_url, f"image non rehebergee ({type(exc).__name__})"
    except Exception as exc:  # noqa: BLE001 - best-effort : une image ne doit jamais bloquer la publication
        logger.exception("Echec inattendu reheberge image")
        return image_url, f"image non rehebergee ({type(exc).__name__})"


# --------------------------------------------------------------------------
# Recherche venue / event
# --------------------------------------------------------------------------

def _find_venue(handle: str, venue_name: str) -> tuple[dict | None, str]:
    """
    Retourne (venue, "") si trouvee de facon certaine, sinon (None, raison)
    avec raison = "no_venue" ou "ambiguous_venue".
    1) correspondance exacte sur l'URL Instagram (requete ciblee)
    2) secours : nom approximatif, uniquement s'il n'y a aucune ambiguite
    """
    if handle and re.fullmatch(r"[a-z0-9._]+", handle):
        rows = _request(
            "GET", "venues",
            params={
                "select": VENUE_COLUMNS,
                "instagram_url": f"ilike.*instagram.com/{handle}*",
                "limit": "20",
            },
        ) or []
        exact = [r for r in rows if _normalize_handle(r.get("instagram_url") or "") == handle]
        if len(exact) == 1:
            return exact[0], ""
        if len(exact) > 1:
            return None, "ambiguous_venue"

    words = [w for w in _normalize_text(venue_name).split() if len(w) >= 3]
    if not words:
        return None, "no_venue"
    token = max(words, key=len)
    rows = _request(
        "GET", "venues",
        params={"select": VENUE_COLUMNS, "name": f"ilike.*{token}*", "limit": "50"},
    ) or []
    scored = sorted(
        ((_similarity(venue_name, r.get("name") or ""), r) for r in rows),
        key=lambda x: x[0], reverse=True,
    )
    if not scored or scored[0][0] < VENUE_NAME_SIMILARITY_MIN:
        return None, "no_venue"
    if len(scored) > 1 and scored[0][0] - scored[1][0] < VENUE_NAME_MARGIN and scored[1][0] >= VENUE_NAME_SIMILARITY_MIN:
        return None, "ambiguous_venue"
    return scored[0][1], ""


def _find_existing_event(venue_id: str, start_utc: datetime, titre: str) -> dict | None:
    """Meme venue + date a +/- 2 jours (heure de Bali) + titre proche."""
    margin = timedelta(days=DATE_WINDOW_DAYS + 1)
    rows = _request(
        "GET", "events",
        params=[
            ("select", EVENT_COLUMNS),
            ("id_venue", f"eq.{venue_id}"),
            ("date_time", f"gte.{(start_utc - margin).isoformat()}"),
            ("date_time", f"lte.{(start_utc + margin).isoformat()}"),
            ("order", "date_time.asc"),
            ("limit", "50"),
        ],
    ) or []
    target_day = start_utc.astimezone(settings.BALI_TZ).date()
    best: tuple[float, int, dict] | None = None
    for row in rows:
        if not row.get("date_time"):
            continue
        day_gap = abs((_parse_ts(row["date_time"]).astimezone(settings.BALI_TZ).date() - target_day).days)
        if day_gap > DATE_WINDOW_DAYS:
            continue
        sim = _similarity(titre, row.get("title") or "")
        if sim < TITLE_SIMILARITY_MIN:
            continue
        if best is None or (sim, -day_gap) > (best[0], -best[1]):
            best = (sim, day_gap, row)
    return best[2] if best else None


# --------------------------------------------------------------------------
# Publication
# --------------------------------------------------------------------------

def _result(status: str, message: str, event_id: str | None = None) -> dict:
    return {"status": status, "event_id": event_id, "message": f"V2: {message}"}


def _note(image_note: str) -> str:
    return f" ATTENTION: {image_note}." if image_note else ""


def _publish(record: dict, event_time: tuple[int, int] | None) -> dict:
    global _not_configured_logged
    if not _is_configured():
        if not _not_configured_logged:
            logger.warning("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY manquants - publication V2 ignoree.")
            _not_configured_logged = True
        return _result("skipped_not_configured", "non configuree (secrets Supabase absents), publication V2 ignoree.")

    f = record["fields"]
    venue_name = f.get(settings.FLD_VENUE_NAME, "") or ""
    handle = _normalize_handle(f.get(settings.FLD_INSTAGRAM, "") or "")
    titre = (f.get(settings.FLD_TITRE, "") or "").strip()
    date_str = f.get(settings.FLD_DATE, "") or ""
    caption = f.get(settings.FLD_LEGENDE, "") or ""
    image_url = f.get(settings.FLD_IMAGE_URL, "") or ""

    if not titre or not date_str:
        return _result("skipped_invalid", "titre ou date manquant, publication V2 ignoree.")

    venue, reason = _find_venue(handle, venue_name)
    who = f"'{venue_name}' (@{handle})" if handle else f"'{venue_name}'"
    if not venue:
        if reason == "ambiguous_venue":
            return _result("skipped_ambiguous_venue",
                           f"plusieurs venues correspondent a {who} - non publie sur la V2, a verifier dans le back-office.")
        return _result("skipped_no_venue",
                       f"venue {who} introuvable dans le back-office - non publie sur la V2, a creer dans le back-office.")

    hour, minute = event_time if event_time else (DEFAULT_HOUR_BALI, 0)
    start_utc = _bali_to_utc(date_str, hour, minute)
    # Same convention as the GoodBarber (V1) publication: end of the same
    # day (23:59 Bali time) when no real end date is known.
    end_utc = _bali_to_utc(date_str, 23, 59)
    existing = _find_existing_event(venue["id_venue"], start_utc, titre)

    if existing:
        if (existing.get("source_type") or "") != "scraped":
            return _result("skipped_manual_exists",
                           f"un event cree par l'equipe existe deja pour {who} (id {existing['id_event']}) - non modifie.",
                           existing["id_event"])
        payload: dict = {}
        if titre != existing.get("title"):
            payload["title"] = titre
        # Sans heure precise, on ne remplace pas une heure deja connue par le defaut de 20h.
        existing_dt = _parse_ts(existing["date_time"])
        same_day = existing_dt.astimezone(settings.BALI_TZ).date() == start_utc.astimezone(settings.BALI_TZ).date()
        if event_time or not same_day:
            if existing_dt != start_utc:
                payload["date_time"] = start_utc.isoformat()
        # Only fill end_date_time in if it's not set yet - never override a
        # value staff may have set by hand in the back-office (e.g. for a
        # real multi-day event).
        if not existing.get("end_date_time"):
            payload["end_date_time"] = end_utc.isoformat()
        current_desc = existing.get("description") or ""
        if caption and not current_desc:
            payload["description"] = caption
        elif caption and caption not in current_desc:
            payload["description"] = f"{current_desc}\n\n{caption}"
        image_note = ""
        if image_url:
            existing_image = existing.get("image_url")
            if existing_image != _image_target(image_url)[1]:  # pas deja reheberge
                new_image, image_note = _rehost_image(image_url)
                # Si le reheberge echoue et qu'une image existe deja, on la garde
                # plutot que de la remplacer par une URL Instagram qui va expirer.
                if not (image_note and existing_image):
                    payload["image_url"] = new_image
        if payload:
            _request("PATCH", "events", params={"id_event": f"eq.{existing['id_event']}"},
                     json_body=payload, prefer="return=minimal")
        return _result("updated", f"event mis a jour (id {existing['id_event']}).{_note(image_note)}", existing["id_event"])

    event_id = str(uuid.uuid4())
    stored_image, image_note = _rehost_image(image_url) if image_url else ("", "")
    row = {
        "id_event": event_id,
        "id_venue": venue["id_venue"],
        "title": titre,
        "date_time": start_utc.isoformat(),
        "end_date_time": end_utc.isoformat(),
        "image_url": stored_image or None,
        "market": venue.get("market"),
        "description": caption or None,
        "event_instagram_url": f"https://www.instagram.com/{handle}/" if handle else None,
        "source_type": "scraped",
        "latitude": venue.get("latitude"),
        "longitude": venue.get("longitude"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _request("POST", "events", json_body=row, prefer="return=minimal")
    return _result("created", f"event cree (id {event_id}).{_note(image_note)}", event_id)


def publish_to_supabase(record: dict, event_time: tuple[int, int] | None = None) -> dict:
    """
    Publie (cree ou met a jour) sur la V2 la ligne Airtable `record`.
    `event_time` = (heure, minute) de Bali si connue (deja extraite pour
    GoodBarber, evite un 2e appel Claude), sinon 20h par defaut.

    NE LEVE JAMAIS D'EXCEPTION. Retourne toujours
    {"status": ..., "event_id": ... | None, "message": "V2: ..."} avec status parmi :
    created, updated, skipped_no_venue, skipped_ambiguous_venue,
    skipped_manual_exists, skipped_invalid, skipped_not_configured, error.
    """
    try:
        return _publish(record, event_time)
    except Exception as exc:  # noqa: BLE001 - garde-fou volontaire, voir docstring du module
        logger.exception("Echec publication V2 (Supabase) - GoodBarber non affecte")
        return _result("error", f"erreur Supabase ({type(exc).__name__}: {str(exc)[:300]}) - non publie sur la V2.")
