"""
Client MCP DIRECT pour GoodBarber - version finale, sans passer par Claude.

Corrige suite au retour du support GoodBarber (22 aout 2026) :
- Le serveur utilise le transport "Streamable HTTP" (pas SSE classique,
  malgre le suffixe /mcp/sse historique dans l'URL) -> streamable_http_client.
- Le token stocke auparavant dans Airtable (rafraichi par Make) n'est PAS
  un vrai token d'acces MCP - il faut un vrai flux OAuth (fait UNE FOIS,
  de maniere interactive, via scripts/oauth_bootstrap_goodbarber.py).

Ce module CHARGE l'etat OAuth persiste (Airtable en priorite, sinon la
variable d'environnement GOODBARBER_MCP_OAUTH_STATE issue du bootstrap
initial), et PERSISTE automatiquement tout rafraichissement de token vers
Airtable pour que les prochains runs en beneficient - aucune intervention
humaine requise apres le bootstrap initial.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import httpx2
from pydantic import AnyUrl

from mcp import Client
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from config import settings
from src import airtable_client

logger = logging.getLogger("whatson.goodbarber_mcp")

OAUTH_TOKEN_LABEL = "goodbarber_mcp_oauth"  # ligne dediee, distincte de "current" (ancien systeme Make)


class GoodBarberMCPError(Exception):
    """Erreur lors d'un appel MCP direct a GoodBarber."""


class AirtableTokenStorage(TokenStorage):
    """
    Persiste l'etat OAuth (tokens + infos client) dans la table Airtable
    Token Data, pour que le rafraichissement automatique profite a tous
    les runs suivants sans jamais re-demander d'autorisation interactive.
    """

    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None
        self._loaded = False

    def _load_if_needed(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        state = self._read_from_airtable()
        if state is None:
            state = self._read_from_bootstrap_env()
        if state is None:
            logger.warning(
                "Aucun etat OAuth GoodBarber trouve (ni Airtable, ni GOODBARBER_MCP_OAUTH_STATE). "
                "Le bootstrap initial (scripts/oauth_bootstrap_goodbarber.py) doit etre lance manuellement."
            )
            return

        if state.get("access_token"):
            self._tokens = OAuthToken(
                access_token=state["access_token"],
                refresh_token=state.get("refresh_token"),
                token_type=state.get("token_type", "Bearer"),
                expires_in=state.get("expires_in"),
            )
        if state.get("client_info"):
            self._client_info = OAuthClientInformationFull.model_validate(state["client_info"])

    def _read_from_airtable(self) -> dict | None:
        try:
            records = airtable_client.search_records(
                settings.AIRTABLE_TABLE_TOKENS,
                formula=f"{{Token Label}} = '{OAUTH_TOKEN_LABEL}'",
                max_records=1,
            )
        except Exception as exc:
            logger.warning("Echec lecture etat OAuth depuis Airtable: %s", exc)
            return None
        if not records:
            return None
        raw = records[0]["fields"].get("fldjX3lvP5GYdDHnU", "")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Etat OAuth Airtable illisible (JSON invalide).")
            return None

    def _read_from_bootstrap_env(self) -> dict | None:
        raw = os.environ.get("GOODBARBER_MCP_OAUTH_STATE", "")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("GOODBARBER_MCP_OAUTH_STATE illisible (JSON invalide).")
            return None

    def _persist_to_airtable(self) -> None:
        state = {
            "access_token": self._tokens.access_token if self._tokens else None,
            "refresh_token": self._tokens.refresh_token if self._tokens else None,
            "token_type": self._tokens.token_type if self._tokens else "Bearer",
            "expires_in": self._tokens.expires_in if self._tokens else None,
            "client_info": self._client_info.model_dump(mode="json") if self._client_info else None,
        }
        try:
            existing = airtable_client.search_records(
                settings.AIRTABLE_TABLE_TOKENS,
                formula=f"{{Token Label}} = '{OAUTH_TOKEN_LABEL}'",
                max_records=1,
            )
            payload = {"fldjX3lvP5GYdDHnU": json.dumps(state)}
            if existing:
                airtable_client.update_record(settings.AIRTABLE_TABLE_TOKENS, existing[0]["id"], payload)
            else:
                airtable_client.create_record(
                    settings.AIRTABLE_TABLE_TOKENS,
                    {"fldi0aaz8BmEPzU80": OAUTH_TOKEN_LABEL, **payload},
                )
            logger.info("Etat OAuth GoodBarber persiste dans Airtable (rafraichissement).")
        except Exception as exc:
            logger.error("Echec persistance etat OAuth vers Airtable: %s", exc)

    async def get_tokens(self) -> OAuthToken | None:
        self._load_if_needed()
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens
        self._persist_to_airtable()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        self._load_if_needed()
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info
        self._persist_to_airtable()


async def _refuse_interactive(*args, **kwargs):
    """Les runs automatises ne doivent JAMAIS necessiter d'autorisation
    interactive - si le SDK appelle ceci, c'est que le bootstrap initial
    n'a pas ete fait ou que le refresh_token est invalide/revoque."""
    raise GoodBarberMCPError(
        "Autorisation interactive requise mais impossible en environnement automatise. "
        "Le bootstrap OAuth (scripts/oauth_bootstrap_goodbarber.py) doit etre relance manuellement."
    )


def _build_oauth_provider() -> OAuthClientProvider:
    return OAuthClientProvider(
        server_url=settings.GOODBARBER_MCP_URL,
        client_metadata=OAuthClientMetadata(
            client_name="WhatsOn Agenda Automation",
            application_type="native",
            redirect_uris=[AnyUrl("http://127.0.0.1:8765/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=AirtableTokenStorage(),
        redirect_handler=_refuse_interactive,
        callback_handler=_refuse_interactive,
    )


async def _list_tools_async(step_timeout: float = 30.0) -> list[dict]:
    oauth = _build_oauth_provider()
    async with httpx2.AsyncClient(auth=oauth, follow_redirects=True) as http_client:
        transport = streamable_http_client(settings.GOODBARBER_MCP_URL, http_client=http_client)
        async with Client(transport) as client:
            result = await asyncio.wait_for(client.list_tools(), timeout=step_timeout)
            return [{"name": t.name, "description": t.description} for t in result.tools]


def list_tools() -> list[dict]:
    """Version synchrone (wrapper) - liste les outils exposes par le serveur MCP GoodBarber."""
    try:
        return asyncio.run(_list_tools_async())
    except GoodBarberMCPError:
        raise
    except Exception as exc:
        raise GoodBarberMCPError(f"Echec connexion/decouverte MCP: {type(exc).__name__}: {exc}") from exc
