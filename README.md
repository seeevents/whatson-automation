# WhatsOn Automation (remplacement de Make)

R�écriture en Python du pipeline WhatsOn (SEE Events Bali), pour remplacer
Make.com et éliminer son coût par crédit/module.

## État d'avancement

- [x] Structure du projet
- [x] Connecteur Airtable (REST direct)
- [x] Connecteur Claude API (avec support `mcp_servers`)
- [x] Connecteur Microsoft Graph (SharePoint/Excel, auth client credentials)
- [x] Connecteur Apify (scraping posts + stories)
- [x] Connecteur Gemini Vision (fallback OCR)
- [x] Module **Tri** — teste en conditions reelles, valide
- [x] Module **Publication** — teste (creation, mise a jour, rejet geographique), valide
- [x] Module **Brique 3** — scraping + extraction + dedoublonnage, teste sur batch complet (14/14 comptes, 0 erreur)
- [x] Parallelisation Brique 3 en 8 jobs GitHub Actions (matrice), reproduit l'architecture Make
- [x] Reporting client (Resolve Client File + DirectWrite) et Log Event To Tracking
- [x] Programmation automatique (cron GitHub Actions) : batches 12h00, tri 12h40+12h55, publication 13h00/13h50/14h40 (heure Bali)
- [ ] Fallback dedoublonnage par compte Instagram dans Publication (bug connu, non corrige - couvert par validation manuelle de l'equipe)
- [ ] Les 8 scenarios Make de Brique 3 + Tri + Publication sont desactives, a supprimer definitivement apres quelques jours de suivi sans incident

## Secrets requis (GitHub repo secrets)

| Secret | Description |
|---|---|
| `AIRTABLE_API_KEY` | Personal Access Token Airtable |
| `ANTHROPIC_API_KEY` | Cle API Anthropic |
| `APIFY_API_TOKEN` | Token API Apify |
| `GEMINI_API_KEY` | Cle API Google Gemini (fallback vision) |
| `MICROSOFT_CLIENT_ID` | App Azure AD (SharePoint/Excel) |
| `MICROSOFT_CLIENT_SECRET` | Secret de l'app Azure AD |
| `MICROSOFT_TENANT_ID` | Tenant ID Azure AD |

## Workflows GitHub Actions

| Workflow | Declenchement | Role |
|---|---|---|
| `batch_parallel.yml` | Cron 12h00 Bali (+ manuel) | Scraping + extraction, 8 batches paralleles |
| `tri.yml` | Cron 12h40 + 12h55 Bali (+ manuel) | Classement Valide/Ignore |
| `publication.yml` | Cron 13h00/13h50/14h40 Bali (+ manuel) | Publication GoodBarber + reporting client |
| `publication_test.yml` | Manuel uniquement | Test isole sur un enregistrement precis |
| `test_accounts.yml` | Manuel uniquement | Verifie la lecture InstaCheck |
| `test_one_account.yml` | Manuel uniquement | Test Brique 3 sur un seul compte |
| `test_resolve_client.yml` | Manuel uniquement | Test lecture seule de resolution fichier client |

## Points de vigilance pour la suite

- Le token GoodBarber (OAuth) n'est rafraichi qu'1x/jour sur Make (`Token Refresh`, conserve) alors qu'il expire en principe au bout d'1h - fonctionne en pratique mais mecanisme pas totalement elucide
- Le fallback dedoublonnage par compte Instagram dans Publication ne fonctionne pas (l'API GoodBarber ne permet pas de chercher par `urlEvent`) - a corriger dans une session dediee
- Ne jamais tester le chemin "mise a jour" de Publication sur une venue reelle ayant deja des events en production - toujours utiliser une venue de test fictive

## Architecture

- `config/settings.py` - tous les IDs (Airtable, GoodBarber, SharePoint), aucun secret en dur
- `src/airtable_client.py` - appels REST Airtable
- `src/claude_client.py` - appels API Anthropic, extraction JSON robuste
- `src/msgraph_client.py` - appels Microsoft Graph (lecture InstaCheck, resolution/ecriture fichiers clients)
- `src/apify_client.py` - scraping posts/stories Instagram
- `src/gemini_client.py` - fallback vision (OCR flyers/stories)
- `src/dedup.py` - dedoublonnage posts/stories deja traites
- `src/accounts.py` - filtrage des comptes du jour (jour de semaine + numero de batch)
- `src/extraction.py` - logique Brique 3 (extraction + ecriture Airtable)
- `src/tri.py` - logique metier du Tri
- `src/publication.py` - logique metier de la Publication + reporting client
- `scripts/` - points d'entree executables (production et tests isoles)
