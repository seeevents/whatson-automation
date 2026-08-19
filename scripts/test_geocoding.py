#!/usr/bin/env python3
"""Test isole: geocode un nom de venue, sans rien ecrire nulle part.
Usage: python scripts/test_geocoding.py "Klymax Discotheque"
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import geocoding

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python scripts/test_geocoding.py "<venue_name>"')
        return 1

    venue_name = sys.argv[1]
    result = geocoding.geocode_venue(venue_name)
    if result is None:
        print(f"\n=== Aucun resultat de geocodage pour '{venue_name}' ===")
    else:
        print(f"\n=== Geocodage reussi pour '{venue_name}' ===")
        print(f"  adresse: {result['address']}")
        print(f"  latitude: {result['latitude']}")
        print(f"  longitude: {result['longitude']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
