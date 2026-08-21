#!/usr/bin/env python3
"""Test isole: recupere le HTML oEmbed d'un post Instagram public.
Usage: python scripts/test_oembed.py "https://www.instagram.com/p/XXXXX/"
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import instagram_oembed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python scripts/test_oembed.py "<post_url>"')
        return 1

    post_url = sys.argv[1]
    html = instagram_oembed.get_embed_html(post_url)
    if html is None:
        print(f"\n=== Aucun resultat oEmbed pour '{post_url}' ===")
        return 0

    print(f"\n=== HTML oEmbed recu ({len(html)} caracteres) ===")
    print(html[:1000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
