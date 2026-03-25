"""
Centralized prompt builder for social media post generation.

Three independent axes:
  - Platform (linkedin, facebook, x) → format, length, style rules
  - Objective (audience_growth, job_search, lead_magnet) → mission, CTA, structure
  - use_profile (bool) → inject author context or keep impersonal
"""


# ── Platform-specific rules ──────────────────────────────────────────────

_PLATFORMS = {
    "linkedin": {
        "name": "LinkedIn",
        "role_prefix": "ghostwriter LinkedIn d'élite",
        "hook": """RÈGLE N°1 — LE HOOK (première ligne) :
La première ligne est la PLUS IMPORTANTE. Elle doit stopper le scroll. Techniques :
- Déclaration choc : "J'ai refusé une augmentation de 30%. Voici pourquoi."
- Question provocante : "Et si tout ce qu'on vous a appris sur le management était faux ?"
- Chiffre frappant : "97% des startups échouent. La mienne aussi. 3 fois."
- Histoire personnelle : "Il y a 2 ans, j'ai été viré. Meilleure chose qui me soit arrivée."
- Pattern interrupt : "Arrêtez de chercher votre passion. Sérieusement."
NE COMMENCE JAMAIS par : "🚀 Ravi de...", "Je suis heureux de...", "Aujourd'hui je voudrais..." """,
        "format": """FORMAT LINKEDIN :
- Hook percutant (1 ligne seule) puis ligne vide
- Phrases courtes et percutantes, 1 idée par ligne
- Aère le texte avec des sauts de ligne
- Emojis avec parcimonie (2-4 max, jamais en début de post)
- 3-5 hashtags à la fin (PAS dans le corps du texte)
- Entre 150 et 300 mots
- Écris comme un humain, pas comme un robot corporate
- Retourne UNIQUEMENT le post, sans commentaire ni explication""",
    },
    "facebook": {
        "name": "Facebook",
        "role_prefix": "expert en contenu Facebook viral",
        "hook": """RÈGLE N°1 — L'ACCROCHE :
La première phrase doit capter l'attention dans un fil d'actualité saturé. Techniques :
- Question directe au lecteur : "Tu savais que 80% des gens font cette erreur ?"
- Anecdote courte : "Ce matin, un truc m'a choqué..."
- Déclaration émotionnelle : "Je n'aurais jamais cru dire ça un jour."
- Interpellation : "Si tu es [cible], lis ça jusqu'au bout."
- Confession relatable : "OK, il faut qu'on parle de ce sujet."
NE COMMENCE JAMAIS de manière corporate ou froide.""",
        "format": """FORMAT FACEBOOK :
- Accroche émotionnelle ou interpellante (1-2 lignes)
- Ton conversationnel, comme si tu parlais à un ami
- Paragraphes courts (2-3 lignes max), bien aérés
- Emojis autorisés plus librement (3-6), ils font partie du style Facebook
- PAS de hashtags ou très peu (0-2 max, intégrés naturellement)
- Entre 80 et 200 mots (Facebook récompense les posts plus courts)
- Termine par une question ouverte ou un appel à partager
- Langage simple et accessible, pas de jargon pro
- Retourne UNIQUEMENT le post, sans commentaire ni explication""",
    },
    "x": {
        "name": "X (Twitter)",
        "role_prefix": "expert en contenu viral sur X (Twitter)",
        "hook": """RÈGLE N°1 — IMPACT IMMÉDIAT :
Chaque caractère compte. Le tweet doit frapper dès le premier mot. Techniques :
- Take audacieux : "Hot take : le remote work est surcoté."
- Observation percutante : "Les gens qui réussissent ne postent pas de morning routines."
- Chiffre sec : "2h. C'est le temps qu'on perd en réunions inutiles par jour."
- Question rhétorique : "Pourquoi personne ne parle de ça ?"
- Liste punchy : "3 choses que j'aurais aimé savoir à 25 ans :"
PAS de formules longues, PAS d'introductions. Droit au but.""",
        "format": """FORMAT X (TWITTER) :
- MAXIMUM 280 caractères pour un tweet unique
- Si le sujet demande plus, fais un THREAD (3-7 tweets numérotés 1/, 2/, etc.)
- Chaque tweet du thread doit fonctionner seul ET donner envie de lire la suite
- Le premier tweet du thread est le plus important (c'est le hook)
- Le dernier tweet du thread = CTA ou punchline finale
- Hashtags : 1-2 max, intégrés dans le texte ou à la fin
- Ton direct, punchy, opinions tranchées
- Pas de fioritures, pas de phrases de remplissage
- Les listes marchent très bien (numérotées ou avec tirets)
- Retourne UNIQUEMENT le(s) tweet(s), sans commentaire ni explication
- Pour un thread, sépare chaque tweet par une ligne vide""",
    },
}

# ── Objective-specific prompts ───────────────────────────────────────────

_OBJECTIVES = {
    "audience_growth": {
        "mission": "créer du contenu qui génère un maximum de reach, d'engagement et de followers",
        "instructions": """OBJECTIF : CRÉATION D'AUDIENCE / VIRALITÉ
- L'accroche doit créer un pattern interrupt (curiosité, controverse douce, chiffre choc)
- Optimise pour le reach : rythme dynamique, valeur immédiate
- Provoque la réaction : questions ouvertes, prises de position
- CTA orienté engagement : follow, partage, enregistre, commente""",
    },
    "job_search": {
        "mission": "positionner l'auteur comme un expert crédible et attirer les recruteurs",
        "instructions": """OBJECTIF : RECHERCHE D'EMPLOI
- L'accroche doit démontrer une expertise concrète ou un résultat professionnel
- Mets en avant : compétences techniques, résultats mesurables, apprentissages de carrière
- Personal branding : positionne l'auteur comme expert crédible dans son domaine
- CTA orienté opportunités : ouvert aux opportunités, contactez-moi, DM ouvert""",
    },
    "lead_magnet": {
        "mission": "générer un maximum de commentaires en offrant une ressource de valeur en échange",
        "instructions": """OBJECTIF : LEAD MAGNET — GÉNÉRER DES COMMENTAIRES
- L'accroche doit promettre une ressource/valeur concrète que le lecteur veut absolument
- Le corps donne un APERÇU de la valeur (3-5 points) pour prouver que ça vaut le coup
- Le CTA DOIT être un échange : "Commente [MOT-CLÉ] et je t'envoie [RESSOURCE]"
- Le mot-clé doit être SIMPLE et COURT (1 mot ou 1 emoji)
- TOUJOURS mentionner que c'est GRATUIT""",
    },
}

_NO_PROFILE_RULES = """IMPORTANT — POST IMPERSONNEL :
- PAS de "je", PAS d'anecdote personnelle, PAS de personal branding
- Parle du SUJET, pas de toi : faits, tendances, données, analyses
- Le post doit être informatif, accessible et engageant pour une audience large"""


# ── Builders ─────────────────────────────────────────────────────────────

def _build_profile_block(profile, use_profile):
    """Return profile block + instruction, or no-profile rules."""
    if use_profile and profile:
        return f"\n{profile}\nAdapte le post à ce profil. Utilise un vocabulaire et des exemples cohérents avec son secteur et son audience."
    if not use_profile:
        return f"\n{_NO_PROFILE_RULES}"
    return ""


def _get_platform(platform):
    return _PLATFORMS.get(platform, _PLATFORMS["linkedin"])


def _get_objective(objective):
    return _OBJECTIVES.get(objective, _OBJECTIVES["audience_growth"])


def build_system_prompt(objective, tone, platform="linkedin", profile=None, web_context=None, use_profile=True):
    """
    Build the complete system prompt for post generation.

    Args:
        objective: 'audience_growth', 'job_search', or 'lead_magnet'
        tone: 'professionnel', 'inspirant', 'storytelling', 'educatif', 'humoristique'
        platform: 'linkedin', 'facebook', or 'x'
        profile: result of UserProfile.build_prompt_context() or None
        web_context: enriched web search context or None
        use_profile: whether to inject the user's profile into the prompt
    """
    plat = _get_platform(platform)
    obj = _get_objective(objective)

    role = f"Tu es un {plat['role_prefix']} spécialisé pour {obj['mission']}."

    parts = [
        role,
        "",
        obj["instructions"],
        "",
        plat["hook"],
        "",
        f"TON : {tone}",
        "",
        plat["format"],
    ]

    parts.append(_build_profile_block(profile, use_profile))

    if web_context:
        parts.append("")
        parts.append(web_context)

    return "\n".join(parts)


def build_variants_system_prompt(objective, tone, num_variants, platform="linkedin", profile=None, web_context=None, use_profile=True):
    """Build the system prompt for multi-variant generation."""
    plat = _get_platform(platform)
    obj = _get_objective(objective)

    role = f"Tu es un {plat['role_prefix']} spécialisé pour {obj['mission']}. Génère {num_variants} variantes RADICALEMENT DIFFÉRENTES."

    parts = [
        role,
        "",
        obj["instructions"],
        "",
        plat["hook"],
        "",
        f"""CHAQUE VARIANTE doit avoir :
- Un angle et une structure narrative différente
- Une accroche utilisant une technique différente des autres variantes
- Ton : {tone}""",
        "",
        plat["format"],
        "",
        """IMPORTANT : Sépare les variantes par "---VARIANTE---" (exactement ce séparateur).
Ne numérote pas, commence directement par le contenu.
Retourne UNIQUEMENT les posts, sans introduction ni commentaire.""",
    ]

    parts.append(_build_profile_block(profile, use_profile))

    if web_context:
        parts.append("")
        parts.append(web_context)

    return "\n".join(parts)


def build_single_variant_prompt(objective, tone, platform="linkedin", profile=None, use_profile=True):
    """Build the system prompt for regenerating a single variant."""
    plat = _get_platform(platform)
    obj = _get_objective(objective)

    role = f"Tu es un {plat['role_prefix']} spécialisé pour {obj['mission']}. Génère UNE SEULE nouvelle variante."

    parts = [
        role,
        "",
        obj["instructions"],
        "",
        plat["hook"],
        "",
        f"TON : {tone}",
        "",
        plat["format"],
        "",
        "L'angle et l'accroche doivent être DIFFÉRENTS des variantes existantes.",
    ]

    parts.append(_build_profile_block(profile, use_profile))

    return "\n".join(parts)


# Valid values for validation
VALID_OBJECTIVES = list(_OBJECTIVES.keys())
VALID_PLATFORMS = list(_PLATFORMS.keys())
VALID_TONES = ['professionnel', 'inspirant', 'storytelling', 'educatif', 'humoristique']
