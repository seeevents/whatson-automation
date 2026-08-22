#!/usr/bin/env python3
"""
Script d'AUTORISATION UNIQUE - a lancer UNE SEULE FOIS sur un ordinateur
local (PAS sur GitHub Actions - necessite un navigateur et une connexion
interactive). Obtient le vrai token d'acces MCP GoodBarber + un token de
rafraichissement, qui permettra ensuite a l'automatisation de fonctionner
sans aucune intervention humaine.

Usage:
    pip install mcp==2.0.0 httpx2
    python oauth_bootstrap_goodbarber.py

Suivez les instructions affichees a l'ecran.
"""
import asyncio
import json
import webbrowser
from urllib.parse import parse_qs, urlparse

import httpx2
from pydantic import AnyUrl

from mcp import Client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

MCP_URL = "https://mcp.goodbarber.dev/2940713/mcp/sse"
CALLBACK_URL = "http://127.0.0.1:8765/callback"


class MemoryTokenStorage(TokenStorage):
    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


async def open_authorization_page(url: str) -> None:
    print("\n" + "=" * 70)
    print("Ouverture de la page d'autorisation dans votre navigateur...")
    print("Si elle ne s'ouvre pas automatiquement, copiez cette adresse :")
    print(url)
    print("=" * 70 + "\n")
    webbrowser.open(url)


async def receive_callback() -> AuthorizationCodeResult:
    print(
        "\nUne fois connecte(e) et l'autorisation acceptee dans le navigateur,\n"
        "celui-ci va essayer de charger une page qui ne s'affichera pas\n"
        "(normal, c'est une adresse locale). COPIEZ L'ADRESSE COMPLETE qui\n"
        "apparait dans la barre d'adresse du navigateur a ce moment-la.\n"
    )
    callback_url = await asyncio.to_thread(input, "Collez l'adresse complete ici puis appuyez sur Entree : ")
    parameters = parse_qs(urlparse(callback_url).query)
    return AuthorizationCodeResult(
        code=parameters["code"][0],
        state=parameters.get("state", [None])[0],
        iss=parameters.get("iss", [None])[0],
    )


async def main() -> None:
    storage = MemoryTokenStorage()

    oauth = OAuthClientProvider(
        server_url=MCP_URL,
        client_metadata=OAuthClientMetadata(
            client_name="WhatsOn Agenda Automation",
            application_type="native",
            redirect_uris=[AnyUrl(CALLBACK_URL)],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=storage,
        redirect_handler=open_authorization_page,
        callback_handler=receive_callback,
    )

    async with httpx2.AsyncClient(auth=oauth, follow_redirects=True) as http_client:
        transport = streamable_http_client(MCP_URL, http_client=http_client)
        async with Client(transport) as client:
            result = await client.list_tools()
            print(f"\nConnexion reussie ! {len(result.tools)} outil(s) disponible(s).\n")

    if storage.tokens is None:
        print("ECHEC : aucun token obtenu.")
        return

    # Regroupe tout ce qu'il faut persister en UN SEUL bloc JSON, pour ne
    # creer qu'un seul secret GitHub plutot que plusieurs.
    state = {
        "access_token": storage.tokens.access_token,
        "refresh_token": storage.tokens.refresh_token,
        "token_type": storage.tokens.token_type,
        "expires_in": storage.tokens.expires_in,
        "client_info": storage.client_info.model_dump(mode="json") if storage.client_info else None,
    }

    print("=" * 70)
    print("SUCCES - copiez le bloc JSON ci-dessous EN ENTIER :")
    print("=" * 70)
    print(json.dumps(state))
    print("=" * 70)
    print(
        "\nAjoutez-le MAINTENANT comme secret GitHub nomme GOODBARBER_MCP_OAUTH_STATE\n"
        "(Settings -> Secrets and variables -> Actions -> New repository secret),\n"
        "puis fermez ce terminal - ne collez jamais ce bloc ailleurs (ni dans le\n"
        "chat, ni dans un fichier non securise)."
    )


if __name__ == "__main__":
    asyncio.run(main())
