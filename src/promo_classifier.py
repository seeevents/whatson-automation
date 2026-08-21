"""
Detection des "pseudo-evenements" (Happy Hour, Ladies Night, promos
generiques de menu/plat) en Python PUR, avec score de confiance. Comme
pour date_extractor.py, l'objectif est d'eliminer les appels Claude sur
les cas clairs, et de ne basculer sur un fallback Claude minimal que
pour les cas vraiment ambigus.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Mots-cles indiquant un "pseudo-evenement" recurrent generique
GENERIC_PROMO_KEYWORDS = [
    r"\bhappy\s*hour\b",
    r"\bladies?\s*night\b",
    r"\bbrunch\b(?!.*\b(dj|live|band|artist)\b)",  # brunch seul, sans artiste mentionne
    r"\bopen\s+daily\b",
    r"\bopen\s+from\b",
    r"\bdrinks?\s+special",
    r"\bhappy\s+hours?\b",
]

# Mots-cles indiquant un VRAI element distinctif (annule la detection generique ci-dessus)
DISTINCTIVE_EVENT_KEYWORDS = [
    r"\bdj\s+\w+",  # "DJ Somebody" - DJ suivi d'un nom
    r"\blive\s+(band|music|performance)\b",
    r"\bfeaturing\b",
    r"\bwith\s+special\s+guest",
    r"\bb2b\b",  # back-to-back DJ sets, signal de line-up specifique
    r"\bline[\s-]?up\b",
]

# Mots-cles indiquant une promo de menu/plat specifique (pas un event)
MENU_PROMO_KEYWORDS = [
    r"\bidr\s*[\d,.]+k?\b",  # prix en roupies indonesiennes
    r"\bnew\s+on\s+the\s+menu\b",
    r"\bsignature\s+(dish|cocktail)\b",
    r"\btry\s+our\b",
]


@dataclass
class PromoClassificationResult:
    is_generic_promo: bool
    confidence: str  # "high" ou "low"
    reason: str


def classify_promo(text: str) -> PromoClassificationResult:
    """
    Determine si le texte decrit un "pseudo-evenement" generique
    (Happy Hour, Ladies Night, promo menu) a IGNORER, ou un vrai
    evenement a VALIDER, en Python pur (mots-cles).
    Retourne confidence="low" si le signal est mixte/ambigu (ex: contient
    a la fois "Ladies Night" ET un nom de DJ - laisse Claude trancher).
    """
    if not text:
        return PromoClassificationResult(False, "high", "texte vide, rien a classifier ici")

    t = text.lower()

    has_generic_signal = any(re.search(p, t) for p in GENERIC_PROMO_KEYWORDS)
    has_distinctive_signal = any(re.search(p, t) for p in DISTINCTIVE_EVENT_KEYWORDS)
    has_menu_signal = any(re.search(p, t) for p in MENU_PROMO_KEYWORDS)

    if not has_generic_signal and not has_menu_signal:
        # Aucun signal de pseudo-evenement detecte - probablement un vrai event,
        # mais on ne l'affirme pas ici avec confiance (ce module ne fait QUE la
        # detection de promos generiques, pas la validation positive d'un event)
        return PromoClassificationResult(False, "high", "aucun signal de promo generique detecte")

    if has_distinctive_signal:
        # Ex: "Ladies Night with DJ Somebody" - signal distinctif l'emporte
        return PromoClassificationResult(
            False, "high", "signal generique present MAIS element distinctif (DJ/live/lineup) detecte aussi - VALIDE"
        )

    if has_generic_signal and not has_distinctive_signal:
        return PromoClassificationResult(
            True, "high", "signal de pseudo-evenement generique (Happy Hour/Ladies Night/promo) sans element distinctif"
        )

    if has_menu_signal:
        return PromoClassificationResult(
            True, "high", "signal de promo menu/plat specifique detecte (prix, plat signature)"
        )

    # Cas residuel improbable - par prudence, fallback
    return PromoClassificationResult(False, "low", "signal ambigu, fallback recommande")
