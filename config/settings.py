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

# Field IDs (table Events_Tracking)
FLD_TRACK_STATUS = "fldGd8BsmT5vgeY3F"
FLD_TRACK_TITLE_AT_VENUE = "fldcJo5v9sVjBNFGm"
FLD_TRACK_INSTAGRAM_URL = "fldcRx0YCqfMBjUmG"
FLD_TRACK_VENUE = "fldg8ax8wrgsk9twP"
FLD_TRACK_DATE = "fldkx2z1fXuOobKXu"
FLD_TRACK_MESSAGE = "fldmSH6sx0NuhHUCD"
FLD_TRACK_CLIENT_WEBURL = "fldp6sGqgnR2wLyd7"
FLD_TRACK_GOODBARBER_ID = "fldwtAzoNcUIq7WS2"
FLD_TRACK_EDIT_URL = "fldxaBqVObPdBBCry"

# Field IDs (table Events_Collectes) - copiés depuis les blueprints Make existants
FLD_STATUT = "fldL0NhT0BDiEFLSz"
FLD_TITRE = "fldb8n3QgyamRNLC4"
FLD_VENUE_NAME = "fld9SS5uLWAUkFSek"
FLD_INSTAGRAM = "fldoA3F6gjqiFcOha"
FLD_LEGENDE = "fldzt4EIODZJwiaPC"
FLD_DATE = "fldplmRgkYNlWBIw8"
FLD_IMAGE_URL = "fldMGB4o8SA4LDtkM"
FLD_ALERTE = "flddkjVofHvZYrOKU"
FLD_GOODBARBER_ID = "fldwtgHwaZroCLqga"

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
APIFY_ACTOR_POSTS = "shu8hvrXbJbY3Eb9W"
APIFY_ACTOR_STORIES = "gzUBexxCCcFGpHSSQ"

# --- Microsoft Graph (SharePoint / InstaCheck.xlsx) ---
MS_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID", "")
MS_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET", "")
MS_TENANT_ID = os.environ.get("MICROSOFT_TENANT_ID", "")
MS_SITE_ID = "seebalichronicles.sharepoint.com,fd4c4a64-5470-4400-a960-5b7a3656240a,551586c5-de85-480d-b3b0-fc06a902d5ff"
MS_INSTACHECK_FILENAME = "InstaCheck.xlsx"
MS_INSTACHECK_WORKSHEET = "InstaCheck"
# IDs stables confirmes via les blueprints Make existants (evite une recherche par nom a chaque appel)
MS_INSTACHECK_DRIVE_ID = "b!ZEpM_XBUAESpYFt6NlYkCsWGFVWF3g1Is7D8BqkC1f-rcu1dQUyUSoarWrTnKjA9"
MS_INSTACHECK_ITEM_ID = "01WDGNM5FVNBVIOWJBVBHI6SAT5TFHDL4D"

# --- Gemini Vision (fallback OCR stories/posts sans date) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# --- Google Maps Geocoding (adresse/GPS des nouveaux events) ---
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
GEMINI_MODEL = "gemini-3.6-flash"

# --- Dedup tracking (table Airtable separee, evite de retraiter le meme post/story) ---
AIRTABLE_TABLE_DEDUP = "tblITBraE4pexB4Cy"
FLD_DEDUP_DATE = "fldnUzBaDpTg0RVa8"
FLD_DEDUP_URL = "fldvz9Jhk6sQwn3mK"

# --- Traitement par lot ---
MAX_RECORDS_PER_RUN = 2000  # marge large sous la limite de temps GitHub Actions (6h)


def validate_config() -> list[str]:
    """Retourne la liste des variables d'environnement manquantes."""
    missing = []
    for name in ("AIRTABLE_API_KEY", "ANTHROPIC_API_KEY", "APIFY_API_TOKEN"):
        if not os.environ.get(name):
            missing.append(name)
    return missing
