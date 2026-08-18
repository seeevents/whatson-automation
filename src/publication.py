"""
Module de Publication - portage du scénario Make
"WhatsOn - Publication GoodBarber" (ID 6681763), même prompt système,
même logique de dédoublonnage/mise à jour.

Publie chaque ligne "Validé" sur GoodBarber via l'agent Claude + MCP
(mêmes outils que Make utilisait), puis marque la ligne "Rapporté".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from config import settings
from src import airtable_client, claude_client, msgraph_client

logger = logging.getLogger("whatson.publication")

SYSTEM_PROMPT = """Tu es un agent d'integration de donnees strict. Ton role est de publier UN SEUL evenement dans l'app GoodBarber via les outils MCP mis a ta disposition. Tu traites soit UNE ligne source, soit PLUSIEURS lignes sources regroupees (meme venue, meme date - typiquement un festival multi-posts), sans memoire d'aucun autre appel precedent ou suivant.

## CAS MULTI-SOURCES (plusieurs posts pour le meme evenement/venue/date)
Si le message utilisateur contient plusieurs blocs "--- Source N ---" : c'est qu'un meme evenement (festival, soiree a plusieurs artistes/exposants) a genere plusieurs posts Instagram distincts. Dans ce cas UNIQUEMENT, la regle TEXTE ORIGINAL ne s'applique pas telle quelle : tu dois SYNTHETISER intelligemment tous les elements cles de CHAQUE source (line-up complet, tous les artistes/exposants mentionnes, informations pratiques) en UN SEUL texte cohesif qui couvre l'ensemble - ne copie pas une seule source et n'ignore pas les autres. Choisis le titre le plus generique/descriptif de l'evenement global (pas le nom d'un seul artiste) pour le champ Titre.
IMAGES MULTIPLES : Utilise l'image de la Source 1 comme "Image URL" principale (thumbnail de l'event, via cms_create_event/cms_update_event comme d'habitude). En plus de cela, apres avoir cree/mis a jour le paragraphe de texte de synthese, ajoute un paragraphe de type "photo" (via cms_create_event_paragraph, type="photo", originalThumbnail=URL de l'image, caption=nom de l'artiste/element concerne, isThumbnail=false) pour CHAQUE image des sources RESTANTES (Source 2, 3, etc. - pas besoin de redupliquer la Source 1 en paragraphe puisqu'elle sert deja de thumbnail), jusqu'a 8 images au total maximum, en ignorant les doublons d'URL identiques.

## REGLE D'OR - DEDOUBLONNAGE (a ne jamais enfreindre)
Ne cree JAMAIS un nouvel evenement (cms_create_event) si la venue possede DEJA au moins un evenement sur GoodBarber, meme ancien ou expire.

Etape 1 (Dedoublonnage) :
- Execute cms_list_events avec le Nom de la venue fourni ("{nom_venue}").
- SI des resultats sont renvoyes :
  1. Pour chaque candidat, verifie la presence du champ urlEvent. Si urlEvent n'est pas present dans la liste, appelle cms_get_event(id) pour obtenir la fiche complete de l'evenement.
  2. Extrais uniquement le NOM D'UTILISATEUR Instagram de urlEvent (ex: "sunsetbeachbali" depuis "https://www.instagram.com/sunsetbeachbali/") et compare-le au nom d'utilisateur extrait de "{compte_instagram}".
  3. Ne considere un candidat comme une vraie correspondance QUE SI les noms d'utilisateur Instagram correspondent exactement (ignore la casse, les slashes finaux et les variations http/https/www).
  - Si au moins un candidat est confirme par cette verification -> passe a la mise a jour (cms_update_event) sur le plus ancien des candidats confirmes.
  - Si aucun candidat n'est confirme -> traite ce cas comme si cms_list_events n'avait renvoye aucun resultat et passe a l'etape de repli.
- SI AUCUN resultat n'est renvoye (ou aucun confirme) -> execute IMPERATIVEMENT un second cms_list_events avec le compte Instagram brut ("{compte_instagram}"), et applique la meme extraction et verification de nom d'utilisateur sur ces nouveaux resultats.
- SI ET SEULEMENT SI cette seconde recherche ne renvoie toujours aucun resultat confirme -> cree un nouvel evenement (cms_create_event).

Etape 2 (Mise a jour si l'evenement existe) :
- Choisis l'evenement LE PLUS ANCIEN parmi les resultats.
- Recupere la liste complete de ses categories actuelles avant toute modification.
- IMPORTANT - AVANT toute modification, note precisement la DATE DE DEBUT actuelle de cet evenement existant (via cms_get_event si besoin) - tu en auras besoin pour le champ "date_changed" du format de reponse final.
- AVANT de toucher au texte : appelle cms_list_event_paragraphs sur cet evenement et lis le contenu du paragraphe de texte existant.
  - CAS FUSION (l'evenement a ete cree/modifie AUJOURD'HUI meme - regarde sa date de derniere modification si disponible, ou deduis-le du fait que le contenu existant semble deja etre un texte source Instagram recent et coherent avec la venue/date actuelle) ET le nouveau texte source decrit un ELEMENT DIFFERENT non deja mentionne (autre artiste/DJ/exposant/stand que ceux deja presents dans le texte existant) : NE REMPLACE PAS le texte existant. FUSIONNE en ajoutant les nouvelles informations a la suite du texte existant (garde tout ce qui etait deja la, ajoute le nouvel element en dessous, separe par un saut de ligne), pour que l'evenement final liste PROGRESSIVEMENT tous les artistes/elements decouverts au fil des posts. Si le nouvel element est deja mentionne dans le texte existant (meme artiste/info deja presente), ne duplique pas, laisse tel quel.
  - CAS REMPLACEMENT NORMAL (l'evenement existant semble ancien/perime, ou le nouveau texte source decrit clairement le MEME contenu que l'existant, juste reformule) : remplace normalement le texte par le nouveau, comme d'habitude.
- Execute cms_update_event sur cet ID : mets a jour titre, dates, SEO, l'Image URL (pour remplacer le thumbnail, SAUF en cas de fusion ou l'image existante reste pertinente - dans ce cas tu peux ajouter la nouvelle image comme paragraphe photo supplementaire plutot que de remplacer le thumbnail), et les categories (= toutes les categories NON-date existantes + la nouvelle categorie de date fournie). Ne touche JAMAIS a la categorie 'Top Events' (10683231) si elle est presente.
- Utilise cms_update_event_paragraph pour mettre a jour le paragraphe de texte existant avec le contenu fusionne ou remplace (selon le cas ci-dessus), plutot que de le supprimer et le recreer si possible.

Etape 3 (Creation si l'evenement n'existe pas) :
- Execute cms_create_event avec la categorie de date fournie, le titre, SEO, et l'Image URL.

Etape 4 (Contenu du texte) :
- CAS NORMAL (une seule source) : le contenu de ce paragraphe DOIT etre la legende/texte d'origine fournie, copiee MOT POUR MOT (voir regle TEXTE ORIGINAL ci-dessous) - ne redige JAMAIS un texte toi-meme sauf si ce champ est vide ou totalement inexploitable.
- CAS MULTI-SOURCES : utilise le texte de synthese que tu as construit (voir section CAS MULTI-SOURCES ci-dessus).
Le mot "NOUVEAU" designe ici uniquement le nouveau BLOC paragraphe technique a creer sur GoodBarber (car l'event n'en a pas encore) - cela ne signifie PAS qu'il faut rediger un texte nouveau ou reformule dans le cas normal. Ajoute ce texte via cms_create_event_paragraph, avec tout le contenu textuel enveloppe dans des balises <span style="color:#FFFFFF">texte</span>.

## AUTRES REGLES METIER

- PERIMETRE GEOGRAPHIQUE : Verifie que l'evenement a bien lieu A BALI. Si le texte source indique clairement un lieu hors de Bali, ne cree/mets a jour aucun evenement -> reponds avec status="ERROR" et explique la raison dans "message".
- TEXTE ORIGINAL (PRIORITE ABSOLUE, cas normal une seule source uniquement, hors fusion) : Le champ "Texte / legende d'origine" fourni dans le message utilisateur contient la legende REELLE du post Instagram. Si ce champ n'est PAS vide, tu DOIS copier ce texte MOT POUR MOT comme contenu du paragraphe - ne le reformule JAMAIS, ne le resume JAMAIS, ne le remplace JAMAIS par ta propre version, meme si tu penses pouvoir faire mieux ou plus clair. Ne redige un texte toi-meme QUE si ce champ est litteralement vide (chaine vide) ou totalement inexploitable (ex : uniquement des emojis sans aucun sens, caracteres corrompus). Cette regle ne s'applique PAS au cas multi-sources ni au cas de fusion (voir Etape 2 et section CAS MULTI-SOURCES) - dans ces deux cas, tu combines/ajoutes plusieurs textes sources plutot que d'en copier un seul mot pour mot.
- SEO META DESCRIPTION : Genere une meta description SEO de 120 caracteres max en anglais avec des mots-cles longue traine, puis ajoute " #seeeventsbali #ifyouseeyouknow" a la fin.
- URL EVENT : Toujours l'URL du compte Instagram (https://www.instagram.com/{compte}/), jamais une URL de post.
- HEURE ET FUSEAU HORAIRE :
  1. Lis le texte source pour toute mention d'heure (ex: "5pm", "doors at 7", "des 18h"). N'utilise allDay=true QUE si aucune heure n'apparait dans le texte.
  2. CONVERSION UTC+8 (Bali) vers UTC+2 (GoodBarber) : Soustrais STRICTEMENT 6 heures a l'heure de Bali trouvee avant d'envoyer la valeur a GoodBarber (ex: 19h Bali -> 13h GoodBarber). Si la soustraction donne une heure negative (ex: 02h Bali - 6h = 20h), fais passer la date de debut au jour CALENDAIRE PRECEDENT et utilise 20h ce jour-la. Ignore l'heure des anciens contenus.
- DATES SANS DATE EXACTE : Si aucun jour exact n'est fourni mais qu'un jour de la semaine est mentionne (ex: "this Saturday", "MERCREDI"), calcule la prochaine occurrence de ce jour a partir de la date du jour.
- CATEGORIES FIXES : Today=10679997, This Week=10679998, Later=10680000, DJ=16725017, Food=10680003, Kids=10680004, Art=10680005, Sport=10680006, Dance=10680007, Wellness=10680008, Other=10680009. La categorie de DATE (Today/This Week/Later) t'est TOUJOURS fournie deja calculee dans le message utilisateur - utilise-la telle quelle, ne la recalcule JAMAIS toi-meme a partir de la date brute. N'attribue une categorie de TYPE (DJ/Food/etc.) que si le contenu le justifie clairement, sinon Other.
- TITRE : Format strict "{Nom de l'evenement} at {Nom de la venue}".
- META TITLE (champ meta.title, a fournir a CHAQUE cms_create_event ET cms_update_event, sans exception) : Format strict "{Nom de l'evenement} at {Nom de la venue} by SEE Events Bali". Lors d'une mise a jour (reutilisation d'un event existant), REMPLACE TOUJOURS l'ancien meta.title par cette valeur recalculee a partir du titre ACTUEL - ne le laisse jamais tel quel ni vide.
- SLUG (champ slug, URL de l'event) : A CHAQUE cms_update_event (reutilisation d'un event existant), genere et envoie TOUJOURS un nouveau slug derive du titre ACTUEL de l'evenement (tout en minuscules, espaces et caracteres speciaux/accents remplaces par des tirets). Ne laisse JAMAIS l'ancien slug herite de l'event precedent. Lors d'un cms_create_event, fournis ce meme slug calcule.
- VERIFICATION POST-ECRITURE : Fais confiance a la reponse renvoyee par cms_create_event / cms_update_event / cms_create_event_paragraph comme preuve de succes de l'ecriture. Si tu relis l'evenement via cms_get_event ou cms_list_event_paragraphs pour verifier, NE conclus JAMAIS a un echec (status=ERROR) uniquement parce que cette relecture immediate montre encore d'anciennes valeurs : GoodBarber peut mettre quelques secondes a propager un changement en lecture. Ne signale status=ERROR que si l'appel d'ecriture lui-meme a renvoye une erreur explicite.

## FORMAT DE REPONSE - OBLIGATOIRE, STRICT, SANS AUCUNE EXCEPTION
N'ecris JAMAIS de raisonnement, de brouillon, d'hesitation ou de texte explicatif visible, meme avant le JSON final. Ne produis QUE le JSON demande, sans aucun texte avant ni apres, sans balise markdown.
Le champ "date_changed" n'a de sens QUE si status="UPDATED" : mets true si la date de debut du nouvel evenement est DIFFERENTE de la date de debut qui existait AVANT ta modification (= un nouvel evenement/occurrence a pris la place du container existant) ; mets false si la date de debut est restee IDENTIQUE (= simple rafraichissement d'un evenement toujours en cours/a venir, contenu ou image mis a jour). Mets false (valeur par defaut) si status="CREATED" ou "ERROR".
Format : {"status": "CREATED ou UPDATED ou ERROR", "date_changed": true ou false, "goodbarber_id": "identifiant de l'evenement", "message": "court resume de l'action ou de l'erreur"}"""


def _get_goodbarber_access_token() -> str:
    """Lit le token OAuth GoodBarber actuel, rafraîchi périodiquement par
    le scénario Make 'Token Refresh' (conservé pour cette seule fonction)."""
    records = airtable_client.search_records(
        settings.AIRTABLE_TABLE_TOKENS,
        formula="{Token Label} = 'current'",
        max_records=1,
    )
    if not records:
        raise RuntimeError("Aucun token GoodBarber trouvé dans Airtable (table Token Data).")
    import json as _json

    fields = records[0]["fields"]
    token_json = fields.get("fldjX3lvP5GYdDHnU", "{}")  # champ "Token Data JSON"
    return _json.loads(token_json).get("access_token", "")


def _compute_date_category(event_date_str: str) -> str:
    """
    Reproduit exactement la formule Make de calcul de categorie de date :
    - Today si la date de l'event = aujourd'hui (heure Bali)
    - This Week si la date est <= fin de la semaine calendaire en cours (dimanche)
    - Later sinon
    """
    if not event_date_str:
        return "Later"
    try:
        event_date = datetime.strptime(str(event_date_str)[:10], "%Y-%m-%d").date()
    except ValueError:
        return "Later"

    today = datetime.now(settings.BALI_TZ).date()
    if event_date == today:
        return "Today"

    days_until_sunday = 7 - today.isoweekday()  # isoweekday: lundi=1 ... dimanche=7
    end_of_week = today + timedelta(days=days_until_sunday)
    if event_date <= end_of_week:
        return "This Week"
    return "Later"


def _build_user_message(record: dict) -> str:
    f = record["fields"]
    date_event = f.get(settings.FLD_DATE, "")
    categorie = _compute_date_category(date_event)
    return (
        f"Titre : {f.get(settings.FLD_TITRE, '')}\n"
        f"Date de l'evenement : {date_event}\n"
        f"Categorie de date calculee (a utiliser telle quelle, ne la recalcule pas toi-meme) : {categorie}\n"
        f"Nom de la venue : {f.get(settings.FLD_VENUE_NAME, '')}\n"
        f"Compte Instagram (repli si le nom de venue ne donne aucun resultat) : {f.get(settings.FLD_INSTAGRAM, '')}\n"
        f"Texte / legende d'origine : {f.get(settings.FLD_LEGENDE, '')}\n"
        f"Image URL : {f.get(settings.FLD_IMAGE_URL, '')}\n"
        f"Note IA / alerte eventuelle : {f.get(settings.FLD_ALERTE, '')}"
    )


def _describe_status(status: str, date_changed: bool) -> str:
    """Traduit (status, date_changed) en libelle clair pour Events_Tracking."""
    if status == "CREATED":
        return "CREATED (nouvel evenement)"
    if status == "UPDATED":
        return "UPDATED - nouvel evenement (nouvelles dates)" if date_changed else "UPDATED - meme evenement (texte/image rafraichis)"
    return status


def process_one_record(record: dict, access_token: str) -> str:
    """Publie une ligne. Retourne le statut final."""
    record_id = record["id"]
    user_message = _build_user_message(record)

    mcp_servers = [
        {
            "type": "url",
            "url": settings.GOODBARBER_MCP_URL,
            "name": "goodbarber",
            "authorization_token": access_token,
        }
    ]

    try:
        response = claude_client.call_claude(
            SYSTEM_PROMPT, user_message, max_tokens=8192, mcp_servers=mcp_servers
        )
    except claude_client.ClaudeError as exc:
        logger.error("Echec appel Claude/GoodBarber pour %s: %s", record_id, exc)
        airtable_client.update_record(
            settings.AIRTABLE_TABLE_EVENTS,
            record_id,
            {
                settings.FLD_STATUT: settings.STATUT_VALIDE,
                settings.FLD_ALERTE: f"ECHEC AUTOMATIQUE (Publication) : {exc}. A traiter manuellement.",
            },
        )
        return settings.STATUT_VALIDE

    try:
        decision = claude_client.extract_json_from_response(response)
    except claude_client.ClaudeError as exc:
        logger.error("Reponse IA non exploitable pour %s: %s", record_id, exc)
        airtable_client.update_record(
            settings.AIRTABLE_TABLE_EVENTS,
            record_id,
            {
                settings.FLD_STATUT: settings.STATUT_VALIDE,
                settings.FLD_ALERTE: "ERREUR TECHNIQUE (Publication) : reponse IA non exploitable - a verifier manuellement.",
            },
        )
        return settings.STATUT_VALIDE

    status = decision.get("status", "ERROR")
    date_changed = bool(decision.get("date_changed", False))
    message = decision.get("message", "")
    goodbarber_id = decision.get("goodbarber_id", "")

    if status == "ERROR":
        airtable_client.update_record(
            settings.AIRTABLE_TABLE_EVENTS,
            record_id,
            {settings.FLD_STATUT: settings.STATUT_A_VALIDER, settings.FLD_ALERTE: message},
        )
        return settings.STATUT_A_VALIDER

    airtable_client.update_record(
        settings.AIRTABLE_TABLE_EVENTS,
        record_id,
        {
            settings.FLD_STATUT: settings.STATUT_RAPPORTE,
            settings.FLD_ALERTE: message,
            settings.FLD_GOODBARBER_ID: str(goodbarber_id) if goodbarber_id else "",
        },
    )
    _report_to_client_and_tracking(record, status, message, goodbarber_id, date_changed)
    return settings.STATUT_RAPPORTE


def _report_to_client_and_tracking(
    record: dict, status: str, message: str, goodbarber_id: str, date_changed: bool = False
) -> None:
    """
    Best-effort: resout le fichier client de la venue, y ecrit l'event,
    et logue le tout dans Events_Tracking. N'importe quel echec ici est
    capture et logue, mais ne fait jamais echouer la publication elle-meme
    (deja actee sur GoodBarber a ce stade).
    """
    f = record["fields"]
    venue_name = f.get(settings.FLD_VENUE_NAME, "")
    titre = f.get(settings.FLD_TITRE, "")
    date = f.get(settings.FLD_DATE, "")
    instagram = f.get(settings.FLD_INSTAGRAM, "")

    resolved_weburl = ""
    try:
        resolved = msgraph_client.resolve_client_file(venue_name)
        if resolved and resolved["name"] not in ("Events_Tracking.xlsx", "InstaCheck.xlsx") and status != "ERROR":
            resolved_weburl = resolved.get("weburl", "")
            msgraph_client.report_event_to_client(
                resolved["drive_id"], resolved["item_id"], titre, date
            )
    except Exception:
        logger.exception("Echec resolution/ecriture fichier client pour '%s' - on continue", venue_name)

    edit_url = ""
    if status != "ERROR" and goodbarber_id:
        edit_url = f"https://www.see.events/manage/cms/agenda/{goodbarber_id}/edit/"

    try:
        airtable_client.create_record(
            settings.AIRTABLE_TABLE_TRACKING,
            {
                settings.FLD_TRACK_STATUS: _describe_status(status, date_changed),
                settings.FLD_TRACK_TITLE_AT_VENUE: f"{titre} at {venue_name}",
                settings.FLD_TRACK_INSTAGRAM_URL: f"https://www.instagram.com/{instagram}/" if instagram else "",
                settings.FLD_TRACK_VENUE: venue_name,
                settings.FLD_TRACK_DATE: date,
                settings.FLD_TRACK_MESSAGE: message,
                settings.FLD_TRACK_CLIENT_WEBURL: resolved_weburl,
                settings.FLD_TRACK_GOODBARBER_ID: str(goodbarber_id) if goodbarber_id else "",
                settings.FLD_TRACK_EDIT_URL: edit_url,
            },
        )
    except Exception:
        logger.exception("Echec ecriture Events_Tracking pour '%s' - on continue", venue_name)


def _build_grouped_user_message(records: list[dict]) -> str:
    """Construit un message utilisateur multi-sources pour un groupe de
    lignes partageant la meme venue + meme date (typiquement un festival)."""
    first = records[0]["fields"]
    date_event = first.get(settings.FLD_DATE, "")
    categorie = _compute_date_category(date_event)

    header = (
        f"Date de l'evenement : {date_event}\n"
        f"Categorie de date calculee (a utiliser telle quelle, ne la recalcule pas toi-meme) : {categorie}\n"
        f"Nom de la venue : {first.get(settings.FLD_VENUE_NAME, '')}\n"
        f"Compte Instagram (repli si le nom de venue ne donne aucun resultat) : {first.get(settings.FLD_INSTAGRAM, '')}\n\n"
        f"ATTENTION : {len(records)} posts distincts detectes pour cette meme venue/date - "
        f"synthetise-les en UN SEUL evenement (voir section CAS MULTI-SOURCES du prompt systeme).\n"
    )
    sources = []
    for i, record in enumerate(records, start=1):
        f = record["fields"]
        sources.append(
            f"--- Source {i} ---\n"
            f"Titre : {f.get(settings.FLD_TITRE, '')}\n"
            f"Texte / legende d'origine : {f.get(settings.FLD_LEGENDE, '')}\n"
            f"Image URL : {f.get(settings.FLD_IMAGE_URL, '')}\n"
        )
    return header + "\n" + "\n".join(sources)


def process_grouped_records(records: list[dict], access_token: str) -> str:
    """
    Publie un groupe de lignes partageant la meme venue + date (festival
    multi-posts) comme UN SEUL evenement de synthese, puis marque TOUTES
    les lignes du groupe avec le meme resultat.
    """
    venue_name = records[0]["fields"].get(settings.FLD_VENUE_NAME, "")
    user_message = _build_grouped_user_message(records)

    mcp_servers = [
        {
            "type": "url",
            "url": settings.GOODBARBER_MCP_URL,
            "name": "goodbarber",
            "authorization_token": access_token,
        }
    ]

    try:
        response = claude_client.call_claude(
            SYSTEM_PROMPT, user_message, max_tokens=8192, mcp_servers=mcp_servers
        )
        decision = claude_client.extract_json_from_response(response)
    except (claude_client.ClaudeError,) as exc:
        logger.error("Echec appel Claude/GoodBarber (groupe '%s', %d lignes): %s", venue_name, len(records), exc)
        for record in records:
            airtable_client.update_record(
                settings.AIRTABLE_TABLE_EVENTS,
                record["id"],
                {
                    settings.FLD_STATUT: settings.STATUT_VALIDE,
                    settings.FLD_ALERTE: f"ECHEC AUTOMATIQUE (Publication groupee) : {exc}. A traiter manuellement.",
                },
            )
        return settings.STATUT_VALIDE

    status = decision.get("status", "ERROR")
    date_changed = bool(decision.get("date_changed", False))
    message = decision.get("message", "")
    goodbarber_id = decision.get("goodbarber_id", "")

    final_status = settings.STATUT_A_VALIDER if status == "ERROR" else settings.STATUT_RAPPORTE
    for record in records:
        fields = {settings.FLD_STATUT: final_status, settings.FLD_ALERTE: message}
        if final_status == settings.STATUT_RAPPORTE:
            fields[settings.FLD_GOODBARBER_ID] = str(goodbarber_id) if goodbarber_id else ""
        airtable_client.update_record(settings.AIRTABLE_TABLE_EVENTS, record["id"], fields)

    if final_status == settings.STATUT_RAPPORTE:
        # Un seul log tracking + reporting client pour le groupe (evite les doublons de reporting)
        _report_to_client_and_tracking(records[0], status, message, goodbarber_id, date_changed)

    logger.info(
        "Groupe traite: '%s' (%d lignes fusionnees) -> %s", venue_name, len(records), final_status
    )
    return final_status


def _group_key(record: dict) -> tuple[str, str]:
    f = record["fields"]
    venue = str(f.get(settings.FLD_VENUE_NAME, "")).strip().lower()
    date = str(f.get(settings.FLD_DATE, "")).strip()
    return (venue, date)


def run(dry_run_record_ids: list[str] | None = None) -> dict[str, int]:
    """
    Publie toutes les lignes 'Validé' actuelles.
    Les lignes partageant la meme venue + meme date sont regroupees et
    publiees comme UN SEUL evenement de synthese (evite d'ecraser
    plusieurs fois le meme container GoodBarber avec des contenus
    differents - cas des festivals multi-posts).
    Si `dry_run_record_ids` est fourni, ne traite QUE ces IDs précis
    (utilisé pour tester sur des enregistrements isolés, sans toucher
    à la vraie file de production).
    """
    access_token = _get_goodbarber_access_token()

    if dry_run_record_ids:
        records = [
            airtable_client.search_records(
                settings.AIRTABLE_TABLE_EVENTS, formula=f"RECORD_ID()='{rid}'", max_records=1
            )[0]
            for rid in dry_run_record_ids
        ]
    else:
        records = airtable_client.search_records(
            settings.AIRTABLE_TABLE_EVENTS,
            formula=f"{{Statut}} = '{settings.STATUT_VALIDE}'",
            max_records=settings.MAX_RECORDS_PER_RUN,
        )

    logger.info("Publication: %d ligne(s) a traiter", len(records))

    groups: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        key = _group_key(record)
        groups.setdefault(key, []).append(record)

    n_grouped = sum(1 for g in groups.values() if len(g) > 1)
    if n_grouped:
        logger.info(
            "%d groupe(s) multi-sources detecte(s) (memes venue+date), %d ligne(s) au total dans ces groupes",
            n_grouped,
            sum(len(g) for g in groups.values() if len(g) > 1),
        )

    summary: dict[str, int] = {}
    total_units = len(groups)
    for i, group in enumerate(groups.values(), start=1):
        if len(group) == 1:
            result = process_one_record(group[0], access_token)
        else:
            result = process_grouped_records(group, access_token)
        summary[result] = summary.get(result, 0) + 1
        if i % 10 == 0 or i == total_units:
            logger.info("Progression: %d/%d unite(s) traitees (%s)", i, total_units, summary)

    logger.info("Publication terminee: %s", summary)
    return summary
