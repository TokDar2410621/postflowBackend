import json
import logging
from datetime import datetime

from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
import anthropic

from .views import get_user_context

logger = logging.getLogger(__name__)


def validate_infographic(data):
    """Validate the structure of generated infographic data."""
    if not isinstance(data, dict):
        return False
    if not data.get('title'):
        return False
    items = data.get('items', [])
    if not isinstance(items, list) or len(items) < 3:
        return False
    for item in items:
        if not isinstance(item, dict):
            return False
        if not item.get('title') or not item.get('description'):
            return False
    return True


INFOGRAPHIC_TEMPLATE_INSTRUCTIONS = {
    'grid-numbered': """FORMAT: GRILLE NUMEROTEE
- Chaque item a un numero sequentiel (1, 2, 3...)
- Le titre de chaque item est un concept court (3-6 mots max)
- La description est une phrase unique et actionnable (15-25 mots)
- Les items couvrent des aspects distincts et complementaires du sujet
- Progression logique ou regroupement thematique""",

    'checklist': """FORMAT: CHECKLIST / ACTIONS
- Chaque titre commence par un verbe d'action a l'imperatif (Definissez, Evitez, Utilisez, Creez...)
- La description explique COMMENT faire ou POURQUOI c'est important
- Les items sont des bonnes pratiques actionnables immediatement
- Ordonner du plus basique au plus avance""",

    'vs': """FORMAT: COMPARAISON / VS
- Les items vont par paires : item impair = "ce qu'on fait souvent", item pair = "ce qu'il faudrait faire"
- Alterner entre le probleme et la solution
- Titres contrastants (ex: "Publier au hasard" vs "Planifier sa strategie")
- Descriptions qui expliquent l'impact de chaque approche""",
}


@api_view(['POST'])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
def generate_infographic(request):
    topic = request.data.get('topic', '').strip()
    tone = request.data.get('tone', 'professionnel')
    num_items = request.data.get('num_items', 9)
    template = request.data.get('template', '').strip()

    if not topic:
        return Response({'error': 'Le sujet est requis'}, status=status.HTTP_400_BAD_REQUEST)

    num_items = max(6, min(12, int(num_items)))

    user_context = get_user_context(request)

    template_block = ""
    if template and template in INFOGRAPHIC_TEMPLATE_INSTRUCTIONS:
        template_block = f"\n\n{INFOGRAPHIC_TEMPLATE_INSTRUCTIONS[template]}\n"

    system_prompt = f"""Tu es un expert en creation de contenu visuel LinkedIn.
Tu generes le contenu structure d'une infographie au format JSON strict.

REGLES DE CONTENU:
- Le titre principal doit etre ACCROCHEUR et court (8-12 mots max)
- Le sous-titre explique la valeur en 1 phrase courte
- Chaque item a un titre COURT (3-6 mots) et une description CONCISE (15-25 mots)
- Le contenu doit etre en francais
- Le footer_cta est une invitation a suivre/partager (ex: "Suivez-moi pour plus de conseils")
- Adapte le ton: {tone}
{template_block}
REGLES TECHNIQUES:
- Retourne UNIQUEMENT du JSON valide, sans markdown, sans backticks, sans commentaire
- Genere exactement {num_items} items
- Chaque item a obligatoirement: number (int), title (str), description (str)

SCHEMA JSON A RESPECTER:
{{
  "infographic": {{
    "title": "Titre accrocheur de l'infographie",
    "subtitle": "Sous-titre explicatif court",
    "items": [
      {{ "number": 1, "title": "Concept cle", "description": "Description courte et actionnable de ce concept." }},
      {{ "number": 2, "title": "Autre concept", "description": "Explication concise et impactante." }}
    ],
    "footer_cta": "Suivez-moi pour plus de conseils"
  }}
}}

{user_context}"""

    user_message = f"Cree une infographie LinkedIn de {num_items} elements sur le sujet suivant:\n\n{topic}"

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
        infographic = data.get('infographic', data if isinstance(data, dict) and 'items' in data else {})

        if not validate_infographic(infographic):
            return Response(
                {'error': "Structure d'infographie invalide generee par l'IA"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'infographic': infographic,
            'metadata': {
                'topic': topic,
                'tone': tone,
                'generated_at': datetime.now().isoformat(),
            },
        })

    except json.JSONDecodeError as e:
        logger.error(f"Infographic JSON parse error: {e}")
        return Response(
            {'error': "Erreur de parsing de l'infographie. Reessayez."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        return Response(
            {'error': 'Erreur API IA. Reessayez.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as e:
        logger.error(f"Infographic generation error: {e}")
        return Response(
            {'error': 'Erreur interne'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['POST'])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
def generate_infographic_caption(request):
    title = request.data.get('title', '').strip()
    subtitle = request.data.get('subtitle', '').strip()
    items = request.data.get('items', [])
    topic = request.data.get('topic', '').strip()
    tone = request.data.get('tone', 'professionnel')

    if not items or not isinstance(items, list):
        return Response(
            {'error': 'Les elements sont requis'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Build text summary
    items_text = []
    for item in items:
        num = item.get('number', '')
        t = item.get('title', '')
        desc = item.get('description', '')
        items_text.append(f"{num}. {t} - {desc}")

    summary = f"Titre: {title}"
    if subtitle:
        summary += f"\nSous-titre: {subtitle}"
    summary += f"\n\nElements:\n" + "\n".join(items_text)

    user_context = get_user_context(request)

    system_prompt = f"""Tu es un expert LinkedIn qui ecrit des legendes (captions) virales pour accompagner des infographies.

REGLES:
- La legende doit donner envie de lire et sauvegarder l'infographie
- Commence par un HOOK percutant (1ere ligne qui stoppe le scroll)
- Ajoute 2-3 phrases qui resument la valeur de l'infographie
- Termine par un CTA (question ou invitation a commenter/sauvegarder)
- Ajoute une ligne vide puis 3-5 hashtags pertinents
- Ton: {tone}
- Longueur ideale: 800-1200 caracteres
- Utilise des emojis avec parcimonie (2-3 max)
- Ecris en francais
- N'utilise PAS de markdown (pas de ** ou ##)

{user_context}"""

    user_message = f"""Ecris une legende LinkedIn pour cette infographie sur le sujet "{topic or title}".

Contenu de l'infographie:
{summary}"""

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
        logger.error(f"Anthropic API error (infographic caption): {e}")
        return Response(
            {'error': 'Erreur API IA. Reessayez.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as e:
        logger.error(f"Infographic caption generation error: {e}")
        return Response(
            {'error': 'Erreur interne'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
