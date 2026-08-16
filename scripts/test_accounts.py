#!/usr/bin/env python3
"""Test isole: lit InstaCheck et affiche les comptes retenus pour aujourd'hui."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import accounts

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def main() -> int:
    todays_accounts = accounts.get_todays_accounts()
    print(f"\n=== {len(todays_accounts)} comptes retenus ===")
    for a in todays_accounts[:10]:
        print(f"  - {a.venue_name}: {a.instagram_url}")
    if len(todays_accounts) > 10:
        print(f"  ... et {len(todays_accounts) - 10} autres")
    return 0


if __name__ == "__main__":
    sys.exit(main())
