# WhatsOn Automation (remplacement de Make)

Réécriture en Python du pipeline WhatsOn (SEE Events Bali), pour remplacer
Make.com et éliminer son coût par crédit/module.

## État d'avancement

- [x] Structure du projet
- [x] Connecteur Airtable (REST direct)
- [x] Connecteur Claude API (avec support `mcp_servers`)
- [x] Module **Tri** (portage du scénario Make `WhatsOn - Tri Automatisé`)
- [ ] Module **Publication** (portage du scénario Make `WhatsOn - Publication GoodBarber`)
- [ ] Module **Brique 3** (scraping Apify + extraction)
- [ ] Tests en parallèle de Make avant coupure définitive
- [ ] Programmation GitHub Actions (actuellement déclenchement manuel only)

## Secrets requis (GitHub repo secrets)

| Secret | Description |
|---|---|
| `AIRTABLE_API_KEY` | Personal Access Token Airtable (scopes: data.records:read, data.records:write) |
| `ANTHROPIC_API_KEY` | Clé API Anthropic (même organisation que Make) |
| `APIFY_API_TOKEN` | Token API Apify (pour Brique 3) |

## Lancer en local

```bash
pip install -r requirements.txt
export AIRTABLE_API_KEY=...
export ANTHROPIC_API_KEY=...
export APIFY_API_TOKEN=...
python scripts/run_tri.py
```

## Architecture

- `config/settings.py` — tous les IDs Airtable/GoodBarber, aucun secret en dur
- `src/airtable_client.py` — appels REST Airtable (recherche, création, mise à jour)
- `src/claude_client.py` — appels API Anthropic, avec extraction JSON robuste
  (comptage de profondeur d'accolades plutôt que découpage naïf comme sur Make)
- `src/tri.py` — logique métier du Tri (même prompt que Make, validé en production le 13/08)
- `scripts/run_tri.py` — point d'entrée exécutable
