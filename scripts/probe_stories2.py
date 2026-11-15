"""Comparaison ancien vs nouveau traitement des stories (lecture seule)."""
import json, os, sys, random
sys.path.insert(0, os.getcwd())
from datetime import datetime
from src import apify_client, gemini_client, publication_supabase as ps
from src.extraction import _stickers_text

venues = ps._request("GET", "venues", params={"select": "name,instagram_url", "scrape_frequency": "eq.everyday", "client_type": "eq.not_a_client", "limit": "400"}) or []
by = {v["name"]: v for v in venues}
pick = [by[n] for n in by if any(k in n for k in ("Ryoshi", "Porch", "Bloom", "Blue Door"))][:4]
random.seed(11)
pick += random.sample(venues, 5)
n_old = n_new = n_tot = 0
for v in pick:
    user = v["instagram_url"].rstrip("/").split("/")[-1]
    stories = apify_client.scrape_stories(user)
    print(f"::notice::== {v['name']} (@{user}) stories={len(stories)}")
    for s in stories[:4]:
        cands = [c.get("url") for c in (s.get("image_versions2") or {}).get("candidates", []) if c.get("url")]
        vid = next((x.get("url") for x in (s.get("video_versions") or []) if x.get("url")), "")
        ts = datetime.fromtimestamp(int(s["taken_at"])).isoformat() if s.get("taken_at") else ""
        st = _stickers_text(s)
        try:
            old = gemini_client.extract_from_images(cands[:1], published_timestamp=ts)
            new = gemini_client.extract_from_story(cands[:1], video_url=vid, stickers_text=st, venue_name=v["name"], published_timestamp=ts)
        except Exception as exc:
            print(f"::notice::  ERREUR {exc}"); continue
        n_tot += 1; n_old += bool(old.get("titre") or old.get("alerte")); n_new += bool(new.get("titre") or new.get("alerte"))
        print(f"::notice::  {'VIDEO' if vid else 'IMG'} stickers={st[:80]!r}")
        print(f"::notice::    ancien: {json.dumps(old, ensure_ascii=False)[:200]}")
        print(f"::notice::    nouveau: {json.dumps(new, ensure_ascii=False)[:300]}")
print(f"::notice::BILAN stories={n_tot} ancien_non_vide={n_old} nouveau_non_vide={n_new}")
