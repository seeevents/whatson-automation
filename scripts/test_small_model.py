#!/usr/bin/env python3
"""Compare le modele leger (Haiku) au modele principal sur les petites taches
(categorie V2, heure, SEO). Sortie: annotations GitHub."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from src import claude_client, publication_direct as pd, publication_supabase as ps

CASES = [
    ("New Year's Eve at Bartolo", "NYE Dinner Thursday 31st December, from 5pm. Set Menu | IDR 850K ++ per person. Bookings essential."),
    ("NYE at La Brisa", "Enzo Siragusa leads the lineup alongside Seb Zito, Marlie, Geco and Dialect. Doors open 8pm. Tickets and tables selling fast."),
    ("Sunday Roast with Live Band", "Live band from 2pm, roast served all afternoon at Woods Bali."),
    ("Kids Art Workshop", "Painting and crafts for little ones, Saturday 10:30 AM - 12:30 PM."),
    ("Sunset Yoga & Sound Healing", "Join us at 5.30pm for breathwork and a sound bath."),
    ("Padel Americano", "Weekly padel tournament, kick-off 7 PM. All levels welcome."),
    ("Ladies Night", "DJ spinning house all night, free flow for ladies 9pm-11pm."),
    ("Pottery Class", "Hands-on ceramics evening. Starts 6:00pm."),
]

def run(model):
    out = []
    for titre, cap in CASES:
        cat = claude_client.extract_json_from_response(claude_client.call_claude(
            ps.EVENT_CATEGORY_SYSTEM_PROMPT, f"Titre: {titre}\nTexte: {cap}", max_tokens=100, model=model)).get("category")
        tm = claude_client.extract_json_from_response(claude_client.call_claude(
            pd.TIME_SYSTEM_PROMPT, f"Texte: {cap}", max_tokens=50, model=model)).get("time")
        out.append((cat, tm))
    return out

big = run(settings.CLAUDE_MODEL)
small = run(settings.CLAUDE_SMALL_MODEL)
diff = 0
for (t, _), b, s in zip(CASES, big, small):
    same = b == s
    diff += not same
    print(f"::notice::{'OK ' if same else 'DIFF'} {t}: {settings.CLAUDE_MODEL}={b} | {settings.CLAUDE_SMALL_MODEL}={s}")
print(f"::notice::{len(CASES)-diff}/{len(CASES)} identiques")
sys.exit(0)
