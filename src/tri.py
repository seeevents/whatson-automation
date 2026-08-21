"""
Module de Tri automatisé - portage direct du scénario Make
"WhatsOn - Tri Automatisé" (ID 6929927), même prompt, même logique.

Classe chaque ligne "A valider" en Validé/Ignoré, avec correction de date
si nécessaire, en 100% autonome (jamais de pause pour confirmation humaine).

ARCHITECTURE HYBRIDE (objectif explicite : minimiser les credits Anthropic
au strict necessaire, dans une logique de sobriete) : chaque ligne passe
d'abord par des regles Python pures (date_extractor, promo_classifier,
verification geographique, detection calendrier multi-jours). Si TOUS ces
controles sont a haute confiance, la decision est prise SANS appel Claude.
Si UN SEUL controle est incertain, on bascule sur l'appel Claude complet
(comportement identique a avant) pour ne jamais sacrifier la fiabilite.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from config import settings
from src import airtable_client, claude_client, date_extractor, promo_classifier

logger = logging.getLogger("whatson.tri")

# Lieux hors Bali frequemment mentionnes par erreur dans des posts de comptes bases a Bali
NON_BALI_PLACES = [
    r"\bsumba\b", r"\blombok\b", r"\bjava\b(?!\s+coffee)", r"\bflores\b",
    r"\bjakarta\b.*\bevent\b", r"\bitaly\b", r"\beurope\b", r"\bsingapore\b.*\bevent\b",
]

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
- IGNORE explicitement les promos de menu/plat/cocktail (ex: presentation d'un plat signature avec son prix, "Seaside Indulgence", nouveau cocktail du moment) meme si un horaire de service general est mentionne (ex: "Party starts at 2 PM" comme horaire d'ouverture habituel) - ce n'est PAS un evenement, c'est une promotion de carte/menu sans date specifique, tant qu'aucune date exacte ou jour de semaine ponctuel n'est explicitement associe a une occasion particuliere (pas juste l'horaire d'ouverture quotidien du lieu).
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


def _check_geography(text: str) -> tuple[bool, str]:
    """
    Retourne (confiance_haute, is_bali).
    IMPORTANT : une simple detection de mot-cle "Sumba"/"Italy" etc. ne
    suffit PAS a rejeter un event avec confiance - une venue basee a Bali
    peut mentionner un autre lieu en passant sans que l'evenement s'y
    deroule (risque de faux positif trop eleve pour trancher seul en
    Python). On ne renvoie donc JAMAIS is_bali=False avec haute confiance
    ici - une mention suspecte declenche systematiquement le fallback
    Claude, qui a le contexte necessaire pour juger correctement.
    """
    t = text.lower()
    for pattern in NON_BALI_PLACES:
        if re.search(pattern, t):
            return False, True  # confiance BASSE : laisse Claude trancher, ne rejette jamais seul
    return True, True  # haute confiance : rien de suspect detecte


def _count_distinct_weekdays_mentioned(text: str) -> int:
    """Compte le nombre de jours de semaine DIFFERENTS mentionnes - un
    nombre eleve (3+) suggere un calendrier multi-jours (This Week/This
    Month at...), cas nuance qu'on prefere laisser a Claude plutot que
    de deviner en Python."""
    t = text.lower()
    found = {day for day in date_extractor.ALL_WEEKDAYS if re.search(rf"\b{day}\b", t)}
    return len(found)


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


def _try_python_classification(record: dict) -> tuple[bool, str, str]:
    """
    Tente une classification 100% Python (zero appel Claude).
    Retourne (succes, status, date) - succes=False signifie qu'il faut
    basculer sur l'appel Claude complet (cas incertain).
    """
    f = record["fields"]
    caption = f.get(settings.FLD_LEGENDE, "") or ""
    alerte_existing = f.get(settings.FLD_ALERTE, "") or ""
    combined_text = f"{caption} {alerte_existing}"
    today = datetime.now(settings.BALI_TZ).date()

    # Controle 1: calendrier multi-jours ? (3+ jours de semaine differents mentionnes)
    if _count_distinct_weekdays_mentioned(combined_text) >= 3:
        return False, "", ""  # trop nuance pour du Python simple, fallback Claude

    # Controle 2: geographie
    geo_confident, is_bali = _check_geography(combined_text)
    if not geo_confident:
        return False, "", ""
    if not is_bali:
        return True, settings.STATUT_IGNORE, ""

    # Controle 3: promo generique
    promo_result = promo_classifier.classify_promo(combined_text)
    if promo_result.confidence != "high":
        return False, "", ""
    if promo_result.is_generic_promo:
        return True, settings.STATUT_IGNORE, ""

    # Controle 4: date/jour exploitable
    date_result = date_extractor.extract_date(combined_text, today)
    if date_result.confidence != "high":
        return False, "", ""
    if not date_result.date:
        return True, settings.STATUT_IGNORE, ""

    # Tous les controles sont a haute confiance et coherents : VALIDE
    return True, settings.STATUT_VALIDE, date_result.date


def process_one_record(record: dict) -> tuple[str, bool]:
    """
    Traite une ligne. Retourne (statut_final, utilise_python_seul).
    statut_final = 'Validé', 'Ignoré', ou 'A valider' en cas d'échec
    technique (la ligne reste en attente pour le prochain run plutôt que
    d'être perdue silencieusement).
    """
    record_id = record["id"]

    success, status, corrected_date = _try_python_classification(record)
    if success:
        fields = {settings.FLD_STATUT: status, settings.FLD_ALERTE: ""}
        if status == settings.STATUT_VALIDE and corrected_date:
            fields[settings.FLD_DATE] = corrected_date
        airtable_client.update_record(settings.AIRTABLE_TABLE_EVENTS, record_id, fields)
        return status, True

    return _process_via_claude(record), False


def _process_via_claude(record: dict) -> str:
    """Fallback Claude complet - utilise UNIQUEMENT quand la classification
    Python pure n'a pas assez de confiance pour trancher seule."""
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


def run(dry_run_record_ids: list[str] | None = None) -> dict[str, int]:
    """
    Traite toutes les lignes 'A valider' actuelles. Retourne un résumé.
    Si `dry_run_record_ids` est fourni, ne traite QUE ces IDs précis
    (utilisé pour tester sur des enregistrements isolés, sans toucher
    à la vraie file de production).
    """
    if dry_run_record_ids:
        records = []
        for rid in dry_run_record_ids:
            found = airtable_client.search_records(
                settings.AIRTABLE_TABLE_EVENTS, formula=f"RECORD_ID()='{rid}'", max_records=1
            )
            if found:
                records.append(found[0])
            else:
                logger.warning("ID '%s' introuvable (deja traite ou supprime) - ignore", rid)
    else:
        records = airtable_client.search_records(
            settings.AIRTABLE_TABLE_EVENTS,
            formula=f"{{Statut}} = '{settings.STATUT_A_VALIDER}'",
            max_records=settings.MAX_RECORDS_PER_RUN,
        )
    logger.info("Tri: %d ligne(s) a traiter", len(records))

    summary = {"Validé": 0, "Ignoré": 0, "A valider": 0}
    python_only_count = 0
    total = len(records)
    for i, record in enumerate(records, start=1):
        result, used_python_only = process_one_record(record)
        if used_python_only:
            python_only_count += 1
        summary[result] = summary.get(result, 0) + 1
        if i % 10 == 0 or i == total:
            logger.info(
                "Progression: %d/%d traitees (%s) - %d/%d sans appel Claude (%.0f%%)",
                i, total, summary, python_only_count, i, 100 * python_only_count / i,
            )

    logger.info("Tri termine: %s - %d/%d lignes traitees en Python pur (%.0f%%)",
                summary, python_only_count, total, 100 * python_only_count / total if total else 0)
    return summary
