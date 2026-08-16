#!/usr/bin/env python3
"""
Test isole: resout UNIQUEMENT le fichier client d'une venue, sans rien
ecrire nulle part (ni GoodBarber, ni le fichier client). Verifie juste
que la mecanique de resolution fonctionne.
Usage: python scripts/test_resolve_client.py "Klymax Discotheque"
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import msgraph_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.test_resolve_client")


def main() -> int:
    if len(sys.argv) < 2:
        logger.error('Usage: python scripts/test_resolve_client.py "<venue_name>"')
        return 1

    venue_name = sys.argv[1]
    logger.warning("MODE TEST LECTURE SEULE - aucune ecriture ne sera faite")

    result = msgraph_client.resolve_client_file(venue_name)
    if result is None:
        print(f"\n=== Aucun fichier client resolu pour '{venue_name}' ===")
    else:
        print(f"\n=== Fichier client resolu pour '{venue_name}' ===")
        print(f"  name: {result['name']}")
        print(f"  item_id: {result['item_id']}")
        print(f"  drive_id: {result['drive_id']}")
        print(f"  weburl: {result['weburl']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
