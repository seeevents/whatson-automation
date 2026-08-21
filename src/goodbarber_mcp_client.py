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


async def _list_tools_async(access_token: str, step_timeout: float = 20.0) -> list[dict]:
    """Se connecte au serveur MCP GoodBarber et liste les outils disponibles.
    Chaque etape a son propre timeout court, avec logs, pour diagnostiquer
    precisement ou ca bloque en cas de probleme (plutot que d'attendre le
    timeout global du job GitHub Actions sans aucune information)."""
    headers = {"Authorization": f"Bearer {access_token}"}

    logger.info("Ouverture de la connexion SSE vers %s ...", settings.GOODBARBER_MCP_URL)
    async with sse_client(settings.GOODBARBER_MCP_URL, headers=headers) as (read, write):
        logger.info("Connexion SSE etablie. Creation de la session MCP...")
        async with ClientSession(read, write) as session:
            logger.info("Session creee. Envoi de initialize() (timeout %ss)...", step_timeout)
            try:
                await asyncio.wait_for(session.initialize(), timeout=step_timeout)
            except asyncio.TimeoutError:
                raise GoodBarberMCPError(
                    f"Timeout sur session.initialize() apres {step_timeout}s - "
                    f"la connexion SSE s'ouvre mais le serveur ne repond pas a la "
                    f"poignee de main MCP (initialize)."
                )
            logger.info("initialize() reussi. Envoi de list_tools() (timeout %ss)...", step_timeout)
            try:
                result = await asyncio.wait_for(session.list_tools(), timeout=step_timeout)
            except asyncio.TimeoutError:
                raise GoodBarberMCPError(
                    f"Timeout sur session.list_tools() apres {step_timeout}s - "
                    f"initialize() a reussi mais list_tools() ne repond pas."
                )
            logger.info("list_tools() reussi: %d outil(s) recu(s).", len(result.tools))
            return [
                {"name": t.name, "description": t.description}
                for t in result.tools
            ]


def list_tools(access_token: str) -> list[dict]:
    """Version synchrone (wrapper) - liste les outils exposes par le serveur MCP GoodBarber."""
    try:
        return asyncio.run(_list_tools_async(access_token))
    except GoodBarberMCPError:
        raise
    except Exception as exc:
        raise GoodBarberMCPError(f"Echec connexion/decouverte MCP: {type(exc).__name__}: {exc}") from exc
