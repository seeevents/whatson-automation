#!/usr/bin/env python3
"""
Test isole Brique 3 sur UN SEUL compte, passe en argument.
Usage: python scripts/test_one_account.py "https://www.instagram.com/afterrockbali/" "After Rock"
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import extraction
from src.accounts import Account

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.test_one_account")


def main() -> int:
    if len(sys.argv) < 3:
        logger.error('Usage: python scripts/test_one_account.py "<instagram_url>" "<venue_name>"')
        return 1

    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    account = Account(venue_name=sys.argv[2], instagram_url=sys.argv[1])
    logger.warning("MODE TEST - un seul compte: %s", account)

    try:
        extraction.process_account(account)
    except Exception:
        logger.exception("Echec fatal du test")
        return 1

    logger.info("Test termine avec succes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
