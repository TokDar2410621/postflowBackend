import json
import logging
from datetime import datetime

from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
import anthropic

from .views import get_user_context, get_content_mode
from .billing import check_generation_limit, increment_usage
from .websearch import enrich_context

logger = logging.getLogger(__name__)

VALID_SLIDE_TYPES = {'title', 'content', 'quote', 'cta', 'dialogue', 'stats', 'comparison', 'list', 'image_text', 'highlight'}

CAROUSEL_MODE_INSTRUCTIONS = {
    "job_search": """
OBJECTIF : RECHERCHE D'EMPLOI
- Slide titre : hook qui démontre une expertise ("Comment j'ai [résultat concret] en [durée]")
- Contenu : focus sur compétences, méthodologie, résultats chiffrés
- Slide CTA : "Contactez-moi", "Ouvert aux opportunités", lien profil
- Ton expert et crédible, évite le clickbait""",
    "audience_growth": """
OBJECTIF : CRÉATION D'AUDIENCE / VIRALITÉ
- Slide titre : hook viral, curiosité maximale, chiffre ou controverse
- Contenu : valeur actionnable, astuces concrètes, format facile à consommer
- Slide CTA : "Follow pour plus", "Enregistre ce carrousel", "Partage"
- Rythme dynamique, phrases punchy, chaque slide donne envie de swiper""",
}


def validate_slides(slides):
    """Validate the structure of generated slides."""
    if not isinstance(slides, list) or len(slides) < 2:
        return False
    for slide in slides:
        if not isinstance(slide, dict):
            return False
        if slide.get('type') not in VALID_SLIDE_TYPES:
            return False
    return True


TEMPLATE_INSTRUCTIONS = {
    'step-by-step': """FORMAT: ETAPE PAR ETAPE
- La slide titre utilise le format "Comment [faire X] en [N] etapes" ou "N etapes pour [resultat]"
- Chaque slide content = 1 etape numerotee dans le titre (ex: "Etape 1 : Definir son objectif")
- Les bullets detaillent l'etape avec des actions concretes
- Progression logique du debut a la fin
- La slide CTA invite a sauvegarder ou partager""",

    'storytelling': """FORMAT: STORYTELLING / TRANSFORMATION
- La slide titre pose un probleme relatable ou une situation de depart forte
- Slides 2-3 : le contexte, la difficulte, le moment bas
- Slides 4-5 : le tournant, la prise de conscience, le changement
- Slides 6-7 : les resultats concrets, les lecons apprises
- Utilise un "body" plutot que des bullets pour un style narratif
- La slide CTA demande aux lecteurs de partager leur propre experience""",

    'data': """FORMAT: DATA & CHIFFRES
- La slide titre annonce des chiffres choc ou une tendance forte
- Utilise des slides "stats" pour mettre en avant les chiffres cles (stat_number gros, stat_label et stat_description)
- Alterne entre slides "stats" et slides "content" pour varier le visuel
- Inclure une slide "quote" avec une source credible
- La slide CTA invite a commenter avec ses propres chiffres""",

    'quick-wins': """FORMAT: QUICK WINS / ASTUCES RAPIDES
- La slide titre promet des benefices immediats (ex: "5 astuces pour doubler votre productivite")
- Chaque slide content = 1 astuce actionnable immediatement
- Titres de slides tres courts et directs
- Bullets avec des exemples concrets et applicables aujourd'hui
- La slide CTA invite a enregistrer le post et a tester""",

    'myths': """FORMAT: MYTHES VS REALITE
- La slide titre annonce qu'on va casser des idees recues (ex: "5 mythes sur le management")
- Utilise des slides "comparison" avec left_title="Le mythe" et right_title="La realite"
- left_items = les croyances fausses, right_items = la verite avec arguments
- Alterne avec des slides "highlight" pour les phrases choc
- Ton un peu provocateur pour generer des reactions
- La slide CTA invite a debattre en commentaires""",

    'dialogue': """FORMAT: DIALOGUE Q&A (BULLES DE CHAT)
- La slide titre pose la problematique ou le theme du dialogue
- Les slides intermediaires sont TOUTES de type "dialogue" avec 2 bulles de conversation
- Chaque slide dialogue = 1 echange: une question/probleme a gauche, une reponse/solution a droite
- left_speaker: qui pose la question (ex: "Question", "Le mythe", "Le probleme")
- left_text: la question ou le probleme (court, 10-20 mots max)
- right_speaker: qui repond (ex: "La reponse", "La realite", "La solution")
- right_text: la reponse concrete et actionnable (15-25 mots max)
- Progresser du probleme le plus courant au plus avance
- La slide CTA invite a commenter avec leur propre question""",
}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def generate_carousel(request):
    # Vérifier la limite de générations
    can_generate, error_response = check_generation_limit(request.user)
    if not can_generate:
        return error_response

    topic = request.data.get('topic', '').strip()
    tone = request.data.get('tone', 'professionnel')
    num_slides = request.data.get('num_slides', 7)
    template = request.data.get('template', '').strip()

    if not topic:
        return Response({'error': 'Le sujet est requis'}, status=status.HTTP_400_BAD_REQUEST)

    num_slides = max(5, min(10, int(num_slides)))

    user_context = get_user_context(request)
    mode = get_content_mode(request)

    # Enrichir avec recherche web si nécessaire
    web_context = enrich_context(topic)

    template_block = ""
    if template and template in TEMPLATE_INSTRUCTIONS:
        template_block = f"\n\n{TEMPLATE_INSTRUCTIONS[template]}\n"

    mode_block = CAROUSEL_MODE_INSTRUCTIONS.get(mode, CAROUSEL_MODE_INSTRUCTIONS["audience_growth"])

    system_prompt = f"""Tu es un expert en creation de carousels LinkedIn viraux.
Tu generes le contenu structure d'un carousel au format JSON strict.

REGLES DE DESIGN LINKEDIN (TRES IMPORTANT):
- Les carousels viraux ont 10-20 mots MAX par slide
- Les titres sont COURTS et PERCUTANTS (5-8 mots max)
- Les bullets sont ultra-concis (max 12 mots chacun)
- La slide 1 (titre) doit STOPPER LE SCROLL avec un hook puissant
- La derniere slide (CTA) doit donner une instruction CLAIRE et SPECIFIQUE

REGLES TECHNIQUES:
- Retourne UNIQUEMENT du JSON valide, sans markdown, sans backticks, sans commentaire
- La premiere slide est TOUJOURS de type "title" avec un hook percutant
- La derniere slide est TOUJOURS de type "cta" (call to action)
- Les slides intermediaires peuvent etre: "content", "quote", "dialogue", "stats", "comparison", "list", "image_text", "highlight"
- Chaque slide "content" a soit des "bullets" (2-4 points concis), soit un "body" (paragraphe court)
- Maximum 1 slide "quote" par carousel
- Le contenu doit etre en francais
- Cree un fil narratif logique entre les slides
- VARIE les types de slides pour un carousel visuellement dynamique (ne mets pas que des "content")
- Adapte le ton: {tone}

QUAND UTILISER CHAQUE TYPE DE SLIDE:
- "content" : point cle avec bullets ou paragraphe (polyvalent)
- "stats" : mettre en avant UN chiffre cle percutant (ex: "78%", "+200K", "3x")
- "comparison" : opposer 2 idees, avant/apres, mythe/realite en 2 colonnes
- "list" : liste d'elements avec emojis (conseils, outils, etapes)
- "highlight" : une phrase impact forte, isolee, qui marque les esprits
- "quote" : citation d'un auteur ou expert
- "dialogue" : echange Q&A en bulles de chat
- "image_text" : texte + espace image (utiliser pour slides visuelles)
{template_block}
{mode_block}

SCHEMA JSON A RESPECTER (exemples de chaque type):
{{
  "slides": [
    {{ "type": "title", "title": "Titre accrocheur", "subtitle": "Sous-titre explicatif" }},
    {{ "type": "content", "title": "Point cle", "bullets": ["Point 1", "Point 2", "Point 3"] }},
    {{ "type": "content", "title": "Autre point", "body": "Paragraphe court et impactant." }},
    {{ "type": "stats", "stat_number": "78%", "stat_label": "des managers", "stat_description": "ne savent pas deleguer efficacement" }},
    {{ "type": "comparison", "left_title": "Avant", "left_items": ["Pas de process", "Travail reactif"], "right_title": "Apres", "right_items": ["Process clairs", "Travail proactif"] }},
    {{ "type": "list", "title": "Les outils essentiels", "list_items": [{{ "emoji": "🎯", "text": "Notion pour organiser" }}, {{ "emoji": "⚡", "text": "Slack pour communiquer" }}] }},
    {{ "type": "highlight", "highlight_text": "Le succes n'est pas un accident. C'est un choix quotidien." }},
    {{ "type": "quote", "quote": "Citation inspirante", "author": "Auteur" }},
    {{ "type": "dialogue", "title": "Sujet optionnel", "left_speaker": "Question", "left_text": "texte de la question", "right_speaker": "Reponse", "right_text": "texte de la reponse" }},
    {{ "type": "cta", "title": "Titre final", "cta_text": "Action a faire", "cta_subtitle": "Suivez-moi pour plus" }}
  ]
}}

{user_context}"""

    if web_context:
        system_prompt += f"\n\n{web_context}"

    user_message = f"Cree un carousel LinkedIn de {num_slides} slides sur le sujet suivant:\n\n{topic}"

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text.strip()

        # Strip markdown fences if present
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
            if raw.endswith('```'):
                raw = raw[:-3].strip()

        data = json.loads(raw)
        slides = data.get('slides', data if isinstance(data, list) else [])

        if not validate_slides(slides):
            return Response(
                {'error': 'Structure de slides invalide generee par l\'IA'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        increment_usage(request.user)

        return Response({
            'slides': slides,
            'metadata': {
                'topic': topic,
                'tone': tone,
                'generated_at': datetime.now().isoformat(),
            },
        })

    except json.JSONDecodeError as e:
        logger.error(f"Carousel JSON parse error: {e}")
        return Response(
            {'error': 'Erreur de parsing du carousel. Reessayez.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        return Response(
            {'error': 'Erreur API IA. Reessayez.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as e:
        logger.error(f"Carousel generation error: {e}")
        return Response(
            {'error': 'Erreur interne'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def generate_carousel_caption(request):
    slides = request.data.get('slides', [])
    topic = request.data.get('topic', '').strip()
    tone = request.data.get('tone', 'professionnel')

    if not slides or not isinstance(slides, list):
        return Response(
            {'error': 'Les slides sont requises'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Build a text summary of the carousel content
    slides_text = []
    for i, slide in enumerate(slides):
        parts = []
        if slide.get('title'):
            parts.append(slide['title'])
        if slide.get('subtitle'):
            parts.append(slide['subtitle'])
        if slide.get('body'):
            parts.append(slide['body'])
        if slide.get('bullets'):
            parts.append(' / '.join(slide['bullets']))
        if slide.get('quote'):
            parts.append(f'"{slide["quote"]}"')
        if slide.get('cta_text'):
            parts.append(slide['cta_text'])
        if slide.get('left_text'):
            parts.append(f"{slide.get('left_speaker', 'Q')}: {slide['left_text']}")
        if slide.get('right_text'):
            parts.append(f"{slide.get('right_speaker', 'R')}: {slide['right_text']}")
        # New slide types
        if slide.get('stat_number'):
            parts.append(f"{slide['stat_number']} {slide.get('stat_label', '')}")
        if slide.get('stat_description'):
            parts.append(slide['stat_description'])
        if slide.get('highlight_text'):
            parts.append(slide['highlight_text'])
        if slide.get('left_title') and slide.get('left_items'):
            parts.append(f"{slide['left_title']}: {', '.join(slide['left_items'])}")
        if slide.get('right_title') and slide.get('right_items'):
            parts.append(f"{slide['right_title']}: {', '.join(slide['right_items'])}")
        if slide.get('list_items'):
            parts.append(' / '.join(item.get('text', '') for item in slide['list_items']))
        slides_text.append(f"Slide {i + 1}: {' - '.join(parts)}")

    carousel_summary = '\n'.join(slides_text)

    user_context = get_user_context(request)

    system_prompt = f"""Tu es un expert LinkedIn qui ecrit des legendes (captions) virales pour accompagner des carousels.

REGLES:
- La legende doit donner envie de swiper le carousel
- Commence par un HOOK percutant (1ere ligne qui stoppe le scroll)
- Ajoute 2-3 phrases qui resument la valeur du carousel
- Termine par un CTA (question ou invitation a commenter/partager)
- Ajoute une ligne vide puis 3-5 hashtags pertinents
- Ton: {tone}
- Longueur ideale: 800-1200 caracteres
- Utilise des emojis avec parcimonie (2-3 max)
- Ecris en francais
- N'utilise PAS de markdown (pas de ** ou ##)

{user_context}"""

    user_message = f"""Ecris une legende LinkedIn pour ce carousel sur le sujet "{topic}".

Contenu du carousel:
{carousel_summary}"""

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        caption = response.content[0].text.strip()

        return Response({'caption': caption})

    except anthropic.APIError as e:
        logger.error(f"Anthropic API error (caption): {e}")
        return Response(
            {'error': 'Erreur API IA. Reessayez.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as e:
        logger.error(f"Caption generation error: {e}")
        return Response(
            {'error': 'Erreur interne'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
