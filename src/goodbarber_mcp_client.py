"""
Client MCP DIRECT pour GoodBarber - parle au serveur MCP en Python pur,
sans jamais passer par l'API Anthropic. Utilise le SDK officiel `mcp`
(protocole standard, pas proprietaire a Claude) en transport SSE.

Objectif : deplacer toute la mecanique (dedoublonnage, creation/mise a
jour d'events) hors des couts Anthropic, en ne gardant Claude que pour
les taches necessitant une vraie comprehension du langage (SEO, categorie,
heure, fusion multi-sources).

ETAPE 1 (ce fichier) : validation de connexion + decouverte des outils.
La logique metier complete sera ajoutee une fois la connexion confirmee.
"""
from __future__ import annotations

import asyncio
import logging

from mcp import ClientSession
from mcp.client.sse import sse_client

from config import settings

logger = logging.getLogger("whatson.goodbarber_mcp")


class GoodBarberMCPError(Exception):
    """Erreur lors d'un appel MCP direct a GoodBarber."""


async def _list_tools_async(access_token: str) -> list[dict]:
    """Se connecte au serveur MCP GoodBarber et liste les outils disponibles."""
    headers = {"Authorization": f"Bearer {access_token}"}

    async with sse_client(settings.GOODBARBER_MCP_URL, headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                {"name": t.name, "description": t.description}
                for t in result.tools
            ]


def list_tools(access_token: str) -> list[dict]:
    """Version synchrone (wrapper) - liste les outils exposes par le serveur MCP GoodBarber."""
    try:
        return asyncio.run(_list_tools_async(access_token))
    except Exception as exc:
        raise GoodBarberMCPError(f"Echec connexion/decouverte MCP: {exc}") from exc
