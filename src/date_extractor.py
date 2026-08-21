"""
Extracteur de dates en Python PUR (aucun appel Claude) - vise a couvrir
la majorite des cas de Tri sans credits Anthropic. Retourne toujours un
niveau de confiance : si le resultat n'est pas fiable, le code appelant
doit alors basculer sur un appel Claude minimal, plutot que de deviner.

Objectif explicite (demande utilisateur) : minimiser au maximum les
credits Anthropic utilises, dans une logique de sobriete/ecologie autant
que de cout.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

WEEKDAYS_EN = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "tues": 1, "wed": 2, "weds": 2, "thu": 3, "thur": 3, "thurs": 3,
    "fri": 4, "sat": 5, "sun": 6,
}
WEEKDAYS_FR = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
    "vendredi": 4, "samedi": 5, "dimanche": 6,
}
ALL_WEEKDAYS = {**WEEKDAYS_EN, **WEEKDAYS_FR}
WEEKDAY_PATTERN = "|".join(sorted(ALL_WEEKDAYS.keys(), key=len, reverse=True))

MONTHS = {
    "jan": 1, "january": 1, "janvier": 1,
    "feb": 2, "february": 2, "fevrier": 2, "février": 2,
    "mar": 3, "march": 3, "mars": 3,
    "apr": 4, "april": 4, "avril": 4,
    "may": 5, "mai": 5,
    "jun": 6, "june": 6, "juin": 6,
    "jul": 7, "july": 7, "juillet": 7,
    "aug": 8, "august": 8, "aout": 8, "août": 8,
    "sep": 9, "sept": 9, "september": 9, "septembre": 9,
    "oct": 10, "october": 10, "octobre": 10,
    "nov": 11, "november": 11, "novembre": 11,
    "dec": 12, "december": 12, "decembre": 12, "décembre": 12,
}
MONTH_PATTERN = "|".join(sorted(MONTHS.keys(), key=len, reverse=True))


@dataclass
class DateExtractionResult:
    date: str  # "" si aucune date/jour trouve
    confidence: str  # "high" (Python tranche seul) ou "low" (fallback Claude requis)
    reason: str  # explication courte (pour logs/alerte)
    is_recurring_pattern: bool = False  # "EVERY MONDAY" etc - utile pour la regle Happy Hour


def _next_occurrence(weekday_idx: int, ref_date: date) -> date:
    """Prochaine occurrence de ce jour de semaine a partir de ref_date (incluse si meme jour)."""
    days_ahead = (weekday_idx - ref_date.weekday()) % 7
    return ref_date + timedelta(days=days_ahead)


def extract_date(text: str, reference_date: date) -> DateExtractionResult:
    """
    Tente d'extraire une date/jour exploitable du texte, en Python pur.
    reference_date = date de publication du post (ancrage pour les annees
    ambigues et les jours relatifs "this/next Saturday").
    """
    if not text or not text.strip():
        return DateExtractionResult("", "high", "texte vide")

    t = text.lower()

    # --- Cas 1 : jour recurrent explicite ("every monday", "tous les vendredis") ---
    m = re.search(rf"\b(every|chaque|tous les)\s+({WEEKDAY_PATTERN})s?\b", t)
    if m:
        weekday_idx = ALL_WEEKDAYS[m.group(2)]
        next_date = _next_occurrence(weekday_idx, reference_date)
        return DateExtractionResult(
            next_date.strftime("%Y-%m-%d"), "high",
            f"jour recurrent '{m.group(0)}' -> prochaine occurrence", is_recurring_pattern=True,
        )

    # --- Cas 2 : jour relatif simple ("this saturday", "next friday", "ce samedi") ---
    m = re.search(rf"\b(this|next|ce|cette|ce\s+prochain)\s+({WEEKDAY_PATTERN})\b", t)
    if m:
        weekday_idx = ALL_WEEKDAYS[m.group(2)]
        is_next = m.group(1) in ("next",)
        next_date = _next_occurrence(weekday_idx, reference_date)
        if is_next and next_date == reference_date:
            next_date += timedelta(days=7)
        return DateExtractionResult(
            next_date.strftime("%Y-%m-%d"), "high", f"jour relatif '{m.group(0)}'"
        )

    # --- Cas 3 : jour de semaine seul, sans "this/every" (ex: juste "Saturday") ---
    # Confiance MOYENNE seulement si c'est le SEUL signal temporel - laisse le cas
    # ambigu (pourrait etre une reference passee, ex: "great turnout last Saturday!")
    # au fallback Claude plutot que de deviner.

    # --- Cas 4 : date explicite complete avec annee (DD/MM/YYYY ou similar) ---
    m = re.search(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            parsed = date(year, month, day)
            return DateExtractionResult(parsed.strftime("%Y-%m-%d"), "high", "date explicite DD/MM/YYYY")
        except ValueError:
            pass  # jour/mois inverses ou invalides, laisse au fallback

    # --- Cas 5 : "Month Day" ou "Day Month" SANS annee - ancrage sur reference_date ---
    m = re.search(rf"\b({MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", t)
    if not m:
        m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_PATTERN})\.?\b", t)
        if m:
            day, month_name = int(m.group(1)), m.group(2)
        else:
            month_name = day = None
    else:
        month_name, day = m.group(1), int(m.group(2))

    if month_name and day:
        month_num = MONTHS[month_name]
        # Verifie si une annee explicite suit (ex: "Sept 19th 2026" ou "Sept 19, 2026")
        year_match = re.search(rf"{re.escape(m.group(0))}\D{{0,3}}(\d{{4}})", t)
        if year_match:
            year = int(year_match.group(1))
        else:
            # Pas d'annee explicite : ancrage sur l'annee de publication (jamais l'annee courante par defaut)
            year = reference_date.year
            # Si cette date semble deja loin dans le passe par rapport a la publication
            # (ex: post de janvier qui parle d'un mois deja passe cette annee-la),
            # on la laisse telle quelle (evenement legitimement passe, sera Ignore plus tard)
            # SAUF si la reference est en fin d'annee et le mois cible est tres tot dans
            # l'annee suivante (ex: post de decembre parlant d'un "Jan 5" -> probablement l'annee d'apres)
            if reference_date.month >= 11 and month_num <= 2:
                year += 1
        try:
            parsed = date(year, month_num, day)
            return DateExtractionResult(
                parsed.strftime("%Y-%m-%d"), "high",
                f"date '{m.group(0)}' ancree sur annee de publication ({reference_date.year})",
            )
        except ValueError:
            pass

    # --- Aucun pattern fiable trouve ---
    # Distingue deux cas : "vraiment aucun signal temporel du tout" (haute
    # confiance, IGNORE en toute securite - c'est le cas le plus frequent)
    # vs "un signal ambigu present mais non reconnu avec certitude" (ex:
    # "last Saturday" - jour de semaine mais SANS this/every/next, ou une
    # formulation inhabituelle) - dans ce dernier cas, on prefere le
    # fallback Claude plutot que de deviner.
    has_any_weekday_mention = bool(re.search(rf"\b({WEEKDAY_PATTERN})\b", t))
    has_any_month_mention = bool(re.search(rf"\b({MONTH_PATTERN})\b", t))
    has_any_date_like_number = bool(re.search(r"\b\d{1,2}[/\-]\d{1,2}\b", text))

    if has_any_weekday_mention or has_any_month_mention or has_any_date_like_number:
        return DateExtractionResult(
            "", "low",
            "signal temporel present (jour/mois/nombre) mais formulation non reconnue avec certitude",
        )

    return DateExtractionResult("", "high", "aucun mot-cle temporel du tout (jour/mois/date) - pas d'evenement exploitable")
