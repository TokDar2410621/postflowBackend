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

VALID_SLIDE_TYPES = {'title', 'content', 'quote', 'cta'}


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


@api_view(['POST'])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
def generate_carousel(request):
    topic = request.data.get('topic', '').strip()
    tone = request.data.get('tone', 'professionnel')
    num_slides = request.data.get('num_slides', 7)

    if not topic:
        return Response({'error': 'Le sujet est requis'}, status=status.HTTP_400_BAD_REQUEST)

    num_slides = max(5, min(10, int(num_slides)))

    user_context = get_user_context(request)

    system_prompt = f"""Tu es un expert en creation de carousels LinkedIn viraux.
Tu generes le contenu structure d'un carousel au format JSON strict.

REGLES IMPORTANTES:
- Retourne UNIQUEMENT du JSON valide, sans markdown, sans backticks, sans commentaire
- La premiere slide est TOUJOURS de type "title" avec un titre accrocheur (hook puissant)
- La derniere slide est TOUJOURS de type "cta" (call to action)
- Les slides intermediaires sont de type "content" ou "quote"
- Chaque slide "content" a soit des "bullets" (2-4 points concis), soit un "body" (paragraphe court)
- Maximum 1 slide "quote" par carousel
- Le contenu doit etre en francais
- Les titres sont courts et percutants (5-8 mots max)
- Les bullets sont concis (1 ligne chacun, max 15 mots)
- Cree un fil narratif logique entre les slides
- Adapte le ton: {tone}

SCHEMA JSON A RESPECTER:
{{
  "slides": [
    {{ "type": "title", "title": "Titre accrocheur", "subtitle": "Sous-titre explicatif" }},
    {{ "type": "content", "title": "Point cle", "bullets": ["Point 1", "Point 2", "Point 3"] }},
    {{ "type": "content", "title": "Autre point", "body": "Paragraphe court et impactant." }},
    {{ "type": "quote", "quote": "Citation inspirante", "author": "Auteur" }},
    {{ "type": "cta", "title": "Titre final", "cta_text": "Action a faire", "cta_subtitle": "Suivez-moi pour plus" }}
  ]
}}

{user_context}"""

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
