"""
Configuration centrale du pipeline WhatsOn.
Toutes les valeurs sensibles (clés API, tokens) viennent des variables
d'environnement / secrets GitHub Actions - jamais en dur ici.
"""
import os
from zoneinfo import ZoneInfo

# --- Fuseau horaire de référence (Bali) ---
BALI_TZ = ZoneInfo("Asia/Makassar")  # UTC+8

# --- Airtable ---
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY", "")
AIRTABLE_BASE_ID = "app153dwtSwh2NJFJ"
AIRTABLE_TABLE_EVENTS = "tblOfzsSmciMWOwnB"          # Events_Collectes
AIRTABLE_TABLE_TRACKING = "tblfbpkOy0n6f6qej"        # Events_Tracking
AIRTABLE_TABLE_TOKENS = "tblCmAXfdDhhLYIeB"          # Token Data (GoodBarber OAuth)

# Field IDs (table Events_Collectes) - copiés depuis les blueprints Make existants
FLD_STATUT = "fldL0NhT0BDiEFLSz"
FLD_TITRE = "fldb8n3QgyamRNLC4"
FLD_VENUE_NAME = "fld9SS5uLWAUkFSek"
FLD_INSTAGRAM = "fldoA3F6gjqiFcOha"
FLD_LEGENDE = "fldzt4EIODZJwiaPC"
FLD_DATE = "fldplmRgkYNlWBIw8"
FLD_IMAGE_URL = "fldMGB4o8SA4LDtkM"
FLD_ALERTE = "flddkjVofHvZYrOKU"

# Valeurs du champ Statut (options exactes, sensibles à l'accent)
STATUT_A_VALIDER = "A valider"
STATUT_VALIDE = "Validé"
STATUT_IGNORE = "Ignoré"
STATUT_RAPPORTE = "Rapporté"

# --- Anthropic ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-5"

# --- GoodBarber (via MCP, appelé depuis l'API Anthropic) ---
GOODBARBER_MCP_URL = "https://mcp.goodbarber.dev/2940713/mcp/sse"
GOODBARBER_ACCOUNT_ID = "2940713"

# Catégories GoodBarber (IDs fixes)
CAT_TODAY = "10679997"
CAT_THIS_WEEK = "10679998"
CAT_LATER = "10680000"
CAT_LIVE_BAND = "10680002"
CAT_DJ = "16725017"
CAT_FOOD = "10680003"
CAT_KIDS = "10680004"
CAT_ART = "10680005"
CAT_SPORT = "10680006"
CAT_DANCE = "10680007"
CAT_WELLNESS = "10680008"
CAT_OTHER = "10680009"
CAT_TOP_EVENTS = "10683231"  # jamais touchée automatiquement

# --- Apify (Brique 3) ---
APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN", "")
APIFY_DATASET_PREFIX = "seeeventsbali~whatson-batch-"  # batch-1 à batch-8

# --- Traitement par lot ---
MAX_RECORDS_PER_RUN = 500  # marge large sous la limite de temps GitHub Actions (6h)


def validate_config() -> list[str]:
    """Retourne la liste des variables d'environnement manquantes."""
    missing = []
    for name in ("AIRTABLE_API_KEY", "ANTHROPIC_API_KEY", "APIFY_API_TOKEN"):
        if not os.environ.get(name):
            missing.append(name)
    return missing
