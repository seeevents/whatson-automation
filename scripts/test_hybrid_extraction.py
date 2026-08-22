#!/usr/bin/env python3
"""
Test isole: appelle DIRECTEMENT extraction.process_post() avec un faux
post construit a la main (contourne le scraping Apify ET la dedoublonnage),
pour valider precisement la nouvelle logique hybride Python/Claude.
Ecrit un vrai enregistrement dans Airtable (Events_Collectes) ET marque
une fausse URL dans la table de dedoublonnage - a nettoyer manuellement
apres verification (voir instructions affichees a la fin).
"""
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import extraction
from src.accounts import Account

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.test_hybrid_extraction")


def main() -> int:
    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    # URL unique a chaque run pour ne jamais etre bloque par le dedoublonnage
    fake_id = uuid.uuid4().hex[:12]

    test_cases = [
        {
            "url": f"https://www.instagram.com/p/DEBUG_HYBRID_{fake_id}_A/",
            "caption": "Join us EVERY MONDAY for quiz night with amazing prizes!",
            "timestamp": "2026-08-22T10:00:00.000Z",
            "ownerUsername": "debughybridtest",
            "displayUrl": "https://example.com/fake.jpg",
            "images": [],
            "_expected": "Python + titre minimal (date sure trouvee)",
        },
        {
            "url": f"https://www.instagram.com/p/DEBUG_HYBRID_{fake_id}_B/",
            "caption": "Beautiful sunset view from our rooftop, come relax with us.",
            "timestamp": "2026-08-22T10:00:00.000Z",
            "ownerUsername": "debughybridtest",
            "displayUrl": "https://example.com/fake.jpg",
            "images": [],
            "_expected": "Python seul, zero Claude (aucune date detectee)",
        },
        {
            "url": f"https://www.instagram.com/p/DEBUG_HYBRID_{fake_id}_C/",
            "caption": "Amazing lineup last Saturday, thanks everyone for coming out!",
            "timestamp": "2026-08-22T10:00:00.000Z",
            "ownerUsername": "debughybridtest",
            "displayUrl": "https://example.com/fake.jpg",
            "images": [],
            "_expected": "Claude complet (cas ambigu, fallback)",
        },
    ]

    account = Account(venue_name="DEBUG_HYBRID_TEST_VENUE", instagram_url="https://www.instagram.com/debughybridtest/")

    for case in test_cases:
        expected = case.pop("_expected")
        logger.warning("=== Test: %s ===", expected)
        logger.warning("Caption: %r", case["caption"])
        extraction.process_post(account, case)
        print()

    print("\n=== IMPORTANT: nettoyage manuel necessaire apres verification ===")
    print(f"1. Verifier dans Airtable (Events_Collectes) les 3 lignes venue='DEBUG_HYBRID_TEST_VENUE' puis les supprimer")
    print(f"2. Verifier/nettoyer la table de dedoublonnage (tblITBraE4pexB4Cy) pour les URLs contenant 'DEBUG_HYBRID_{fake_id}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
