"""
Module de Tri automatisé - portage direct du scénario Make
"WhatsOn - Tri Automatisé" (ID 6929927), même prompt, même logique.

Classe chaque ligne "A valider" en Validé/Ignoré, avec correction de date
si nécessaire, en 100% autonome (jamais de pause pour confirmation humaine).
"""
from __future__ import annotations

import logging
from datetime import datetime

from config import settings
from src import airtable_client, claude_client

logger = logging.getLogger("whatson.tri")

SYSTEM_PROMPT = """Tu es un agent de tri strict pour les evenements SEE Bali / WhatsOn. Tu traites une seule ligne (un post ou story Instagram deja extrait par un premier passage IA), sans memoire d'aucune autre ligne traitee avant ou apres.

## TA TACHE
Decide si cette ligne doit etre classee VALIDE (evenement actionnable, a publier) ou IGNORE (pas d'evenement exploitable).

## REGLES DE DECISION
- VALIDE si un jour de la semaine explicite est mentionne dans le texte (ex: 'EVERY MONDAY', 'this Saturday', 'MERCREDI'), meme sans date exacte -> calcule mentalement la prochaine occurrence de ce jour a partir de la date d'aujourd'hui fournie, et renvoie cette date corrigee.
- VALIDE si une date exacte est donnee dans le texte ou deja extraite, et qu'elle n'est pas strictement dans le passe par rapport a aujourd'hui.
- Si l'annee indiquee dans le texte ou deja extraite rend l'evenement chronologiquement impossible (ex: annee passee alors que le post est recent) -> c'est une coquille du createur du flyer, pas une erreur d'extraction : corrige avec l'annee coherente la plus proche dans le futur et classe VALIDE.
- IGNORE si aucune date ni jour de semaine n'est exploitable dans le texte fourni.
- IGNORE si l'evenement est strictement deja passe (date anterieure a aujourd'hui) sans etre un jour recurrent.
- IGNORE explicitement les "pseudo-evenements" recurrents generiques meme s'ils mentionnent un jour de la semaine ou une heure : Happy Hour, Ladies Night, promo boissons, brunch du dimanche recurrent sans line-up/artiste/theme specifique, et toute offre commerciale repetitive sans contenu evenementiel distinctif. Le simple fait d'avoir un jour identifiable (ex: "Happy Hour every Friday") ne suffit PAS a valider ces cas - ce sont des promotions permanentes du lieu, pas des evenements ponctuels a publier.
- ATTENTION - EXCEPTION IMPORTANTE ET FREQUENTE : si le texte mentionne un DJ (nom propre ou "DJ [nom]") ou un live band/artiste live pour ce Happy Hour/Ladies Night/soiree, c'est un VRAI evenement a VALIDER normalement, meme si le titre generique dit "Ladies Night" ou "Happy Hour" - la presence d'un DJ ou d'un live band nomme est TOUJOURS le signal prioritaire qui l'emporte sur le caractere generique du nom de la soiree. Ne rejette jamais une Ladies Night ou un Happy Hour qui cite un DJ ou un groupe live.
- IGNORE si l'evenement n'a manifestement pas lieu a Bali (autre ile indonesienne comme Sumba, ou etranger).
- IGNORE si le texte est un post generique sans evenement precis (ex: horaires d'ouverture hebdomadaires sur les 7 jours, promo generale sans date).
- IGNORE si le contenu ne decrit pas clairement UN evenement (ou une serie d'evenements identifiable, ex: calendrier hebdo/mensuel) avec venue + date + sujet identifiables - un contenu flou, une simple photo d'ambiance sans texte d'evenement, ou une promo generale sans aucun element concret doit etre Ignore.
- IGNORE si le texte concerne une offre d'emploi ou un post non-evenementiel.

## CAS AMBIGUS - REGLE CRITIQUE
Tu dois TOUJOURS trancher, sans jamais attendre de confirmation humaine et sans jamais poser de question. Si le signal temporel ou geographique est faible ou ambigu mais que tu penches pour une decision, prends cette decision quand meme. Dans ce cas uniquement, note tres brievement la raison de l'incertitude dans le champ alert_note (une phrase courte maximum). Si la decision est claire et sans ambiguite, laisse alert_note vide.

## FORMAT DE REPONSE - STRICT, SANS EXCEPTION
N'ecris JAMAIS de raisonnement, de brouillon ou de texte explicatif visible avant ou apres le JSON. Reponds UNIQUEMENT avec un objet JSON, rien d'autre. Le premier caractere de ta reponse DOIT etre { et le dernier DOIT etre }. Le champ alert_note doit rester tres court (une phrase maximum) pour ne jamais risquer de tronquer la reponse.
Format exact : {"status": "Valide" ou "Ignore", "corrected_date": "YYYY-MM-DD si Valide, chaine vide si Ignore", "alert_note": "note courte si signal faible, sinon chaine vide"}"""


def _build_user_message(record: dict) -> str:
    f = record["fields"]
    today = datetime.now(settings.BALI_TZ).strftime("%Y-%m-%d (%A)")
    return (
        f"Date d'aujourd'hui (Bali) : {today}\n"
        f"Titre : {f.get(settings.FLD_TITRE, '')}\n"
        f"Date deja extraite par le premier passage IA : {f.get(settings.FLD_DATE, '')}\n"
        f"Nom de la venue : {f.get(settings.FLD_VENUE_NAME, '')}\n"
        f"Compte Instagram : {f.get(settings.FLD_INSTAGRAM, '')}\n"
        f"Texte / legende d'origine (OCR + caption) : {f.get(settings.FLD_LEGENDE, '')}\n"
        f"Note IA existante (fallback vision etc.) : {f.get(settings.FLD_ALERTE, '')}"
    )


def process_one_record(record: dict) -> str:
    """
    Traite une ligne. Retourne le statut final ('Validé', 'Ignoré', ou
    'A valider' en cas d'échec technique - la ligne reste en attente pour
    le prochain run plutôt que d'être perdue silencieusement).
    """
    record_id = record["id"]
    user_message = _build_user_message(record)

    try:
        response = claude_client.call_claude(SYSTEM_PROMPT, user_message, max_tokens=2048)
    except claude_client.ClaudeError as exc:
        logger.error("Echec appel Claude pour %s: %s", record_id, exc)
        airtable_client.update_record(
            settings.AIRTABLE_TABLE_EVENTS,
            record_id,
            {
                settings.FLD_STATUT: settings.STATUT_A_VALIDER,
                settings.FLD_ALERTE: f"ECHEC AUTOMATIQUE (Tri) : {exc}. A traiter manuellement.",
            },
        )
        return settings.STATUT_A_VALIDER

    try:
        decision = claude_client.extract_json_from_response(response)
    except claude_client.ClaudeError as exc:
        logger.error("Reponse IA non exploitable pour %s: %s", record_id, exc)
        airtable_client.update_record(
            settings.AIRTABLE_TABLE_EVENTS,
            record_id,
            {
                settings.FLD_STATUT: settings.STATUT_IGNORE,
                settings.FLD_ALERTE: "ERREUR TECHNIQUE (Tri) : reponse IA non exploitable (JSON invalide) - a verifier manuellement.",
            },
        )
        return settings.STATUT_IGNORE

    status = decision.get("status", "")
    alert_note = decision.get("alert_note", "")
    corrected_date = decision.get("corrected_date", "")

    if status == "Valide":
        fields = {
            settings.FLD_STATUT: settings.STATUT_VALIDE,
            settings.FLD_ALERTE: alert_note,
        }
        if corrected_date:
            fields[settings.FLD_DATE] = corrected_date
        airtable_client.update_record(settings.AIRTABLE_TABLE_EVENTS, record_id, fields)
        return settings.STATUT_VALIDE
    else:
        airtable_client.update_record(
            settings.AIRTABLE_TABLE_EVENTS,
            record_id,
            {settings.FLD_STATUT: settings.STATUT_IGNORE, settings.FLD_ALERTE: alert_note},
        )
        return settings.STATUT_IGNORE


def run() -> dict[str, int]:
    """Traite toutes les lignes 'A valider' actuelles. Retourne un résumé."""
    records = airtable_client.search_records(
        settings.AIRTABLE_TABLE_EVENTS,
        formula=f"{{Statut}} = '{settings.STATUT_A_VALIDER}'",
        max_records=settings.MAX_RECORDS_PER_RUN,
    )
    logger.info("Tri: %d ligne(s) a traiter", len(records))

    summary = {"Validé": 0, "Ignoré": 0, "A valider": 0}
    total = len(records)
    for i, record in enumerate(records, start=1):
        result = process_one_record(record)
        summary[result] = summary.get(result, 0) + 1
        if i % 10 == 0 or i == total:
            logger.info("Progression: %d/%d traitees (%s)", i, total, summary)

    logger.info("Tri termine: %s", summary)
    return summary
