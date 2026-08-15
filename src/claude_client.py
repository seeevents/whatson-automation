"""
Connecteur API Anthropic - remplace les appels HTTP bruts vers
api.anthropic.com que Make faisait via http:ActionSendData.

Supporte optionnellement mcp_servers (ex: GoodBarber) pour les cas
où Claude doit agir directement sur un outil externe (Publication),
et un mode simple texte->JSON pour les cas de classification (Tri).
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger("whatson.claude")

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_RETRIES = 3


class ClaudeError(Exception):
    """Erreur lors d'un appel à l'API Anthropic."""


def call_claude(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 2048,
    mcp_servers: list[dict[str, Any]] | None = None,
    mcp_beta: bool = False,
) -> dict[str, Any]:
    """
    Appelle l'API Messages d'Anthropic. Retourne la réponse JSON brute
    (le champ `content` contient la liste des blocs de réponse).
    """
    if not ANTHROPIC_API_KEY:
        raise ClaudeError("ANTHROPIC_API_KEY manquant dans l'environnement.")

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    if mcp_servers or mcp_beta:
        headers["anthropic-beta"] = "mcp-client-2025-04-04"

    body: dict[str, Any] = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_message}],
    }
    if mcp_servers:
        body["mcp_servers"] = mcp_servers

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(API_URL, headers=headers, json=body, timeout=300)
            if resp.status_code == 429:
                wait = 5 * attempt
                logger.warning("Anthropic rate-limit (429), retry dans %ss", wait)
                time.sleep(wait)
                continue
            if resp.status_code == 400 and "credit balance" in resp.text.lower():
                raise ClaudeError(
                    "Crédit API Anthropic insuffisant - recharger sur console.anthropic.com/settings/billing"
                )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)
    raise ClaudeError(f"Echec après {MAX_RETRIES} tentatives: {last_error}") from last_error


def extract_json_from_response(response: dict[str, Any]) -> dict[str, Any]:
    """
    Extrait le premier objet JSON valide trouvé dans les blocs texte de la
    réponse (équivalent de la formule Make
    `substring(text; indexOf(text; "{"))` mais plus robuste : cherche la
    dernière accolade fermante correspondante plutôt que de couper au
    premier "{" seul, qui casse si le JSON contient des objets imbriqués.
    """
    text_blocks = [b.get("text", "") for b in response.get("content", []) if b.get("type") == "text"]
    full_text = "".join(text_blocks)

    start = full_text.find("{")
    if start == -1:
        raise ClaudeError(f"Aucun JSON trouvé dans la réponse: {full_text[:200]!r}")

    # Recherche de l'accolade fermante correspondante (comptage de profondeur)
    depth = 0
    for i, char in enumerate(full_text[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = full_text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise ClaudeError(f"JSON invalide extrait: {candidate[:300]!r}") from exc

    raise ClaudeError(f"JSON non terminé dans la réponse: {full_text[:200]!r}")
