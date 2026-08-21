"""
Client Instagram oEmbed - recupere le HTML d'integration officiel d'un
post Instagram (photo/video/reel) pour l'inserer dans un event GoodBarber
via un paragraphe de type "embed", SANS avoir a re-heberger la video
nous-memes (l'API est tokenless depuis le 15 juin 2026 pour le contenu
public). Ne fonctionne QUE pour les posts (pas les stories, ephemeres et
non supportees par ce systeme officiel).
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger("whatson.instagram_oembed")

OEMBED_URL = "https://graph.facebook.com/v25.0/instagram_oembed"
TIMEOUT = 15


class InstagramOEmbedError(Exception):
    """Erreur lors d'un appel a l'API oEmbed Instagram."""


def get_embed_html(post_url: str, max_width: int = 540) -> str | None:
    """
    Retourne le HTML d'integration officiel Instagram pour ce post, ou
    None si echec (best-effort - ne doit jamais faire echouer la
    publication de l'event).
    """
    params = {"url": post_url, "maxwidth": max_width}
    try:
        resp = requests.get(OEMBED_URL, params=params, timeout=TIMEOUT)
        if not resp.ok:
            logger.info("oEmbed sans resultat pour '%s': %s %s", post_url, resp.status_code, resp.text[:200])
            return None
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Echec oEmbed pour '%s': %s", post_url, exc)
        return None

    html = data.get("html")
    if not html:
        return None
    logger.info("oEmbed OK pour '%s' (%d caracteres)", post_url, len(html))
    return html
