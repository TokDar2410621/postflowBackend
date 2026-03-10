import json
import logging

from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
import anthropic

from .views import get_user_context, extract_hashtags

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
def convert_to_carousel(request):
    """Convert a text post into carousel slides."""
    content = request.data.get('content', '').strip()
    tone = request.data.get('tone', 'professionnel')
    num_slides = max(5, min(10, int(request.data.get('num_slides', 7))))

    if not content:
        return Response({'error': 'Le contenu est requis'}, status=status.HTTP_400_BAD_REQUEST)

    if not settings.ANTHROPIC_API_KEY:
        return Response({'error': 'ANTHROPIC_API_KEY is not configured'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    user_context = get_user_context(request)

    system_prompt = f"""Tu es un expert en création de carousels LinkedIn viraux.
Tu transformes un post texte existant en carousel structuré au format JSON.

RÈGLES:
- Extrais les idées clés du post et structure-les en slides
- La première slide est de type "title" avec un hook accrocheur tiré du post
- La dernière slide est de type "cta"
- Les slides intermédiaires sont "content" ou "quote"
- Chaque slide content a soit "bullets" (2-4 points concis), soit "body" (paragraphe court)
- Maximum 1 slide "quote"
- Titres courts (5-8 mots max), bullets ultra-concis (max 12 mots)
- Ton: {tone}
- Retourne UNIQUEMENT du JSON valide, sans backticks, sans commentaire

SCHEMA JSON:
{{
  "slides": [
    {{ "type": "title", "title": "Titre accrocheur", "subtitle": "Sous-titre" }},
    {{ "type": "content", "title": "Point clé", "bullets": ["Point 1", "Point 2", "Point 3"] }},
    {{ "type": "content", "title": "Autre point", "body": "Paragraphe court et impactant." }},
    {{ "type": "quote", "quote": "Citation du post", "author": "Auteur" }},
    {{ "type": "cta", "title": "Titre final", "cta_text": "Action", "cta_subtitle": "Suivez-moi" }}
  ]
}}

{user_context}"""

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Transforme ce post LinkedIn en carousel de {num_slides} slides:\n\n{content}"}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
            if raw.endswith('```'):
                raw = raw[:-3].strip()

        data = json.loads(raw)
        slides = data.get('slides', data if isinstance(data, list) else [])

        return Response({
            'slides': slides,
            'metadata': {'tone': tone},
        })

    except json.JSONDecodeError:
        return Response({'error': 'Erreur de parsing. Réessayez.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        return Response({'error': 'Erreur API IA.'}, status=status.HTTP_502_BAD_GATEWAY)
    except Exception as e:
        logger.error(f"Convert to carousel error: {e}")
        return Response({'error': 'Erreur interne'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
def convert_to_infographic(request):
    """Convert a text post into infographic items."""
    content = request.data.get('content', '').strip()
    tone = request.data.get('tone', 'professionnel')
    num_items = max(6, min(12, int(request.data.get('num_items', 9))))

    if not content:
        return Response({'error': 'Le contenu est requis'}, status=status.HTTP_400_BAD_REQUEST)

    if not settings.ANTHROPIC_API_KEY:
        return Response({'error': 'ANTHROPIC_API_KEY is not configured'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    user_context = get_user_context(request)

    system_prompt = f"""Tu es un expert en création d'infographies LinkedIn.
Tu transformes un post texte existant en infographie structurée au format JSON.

RÈGLES:
- Extrais les idées clés et structure-les en items numérotés
- Le titre doit être accrocheur (8-12 mots max)
- Chaque item a un titre court (3-6 mots) et une description concise (15-25 mots)
- Ton: {tone}
- Retourne UNIQUEMENT du JSON valide, sans backticks, sans commentaire

SCHEMA JSON:
{{
  "infographic": {{
    "title": "Titre accrocheur",
    "subtitle": "Sous-titre explicatif court",
    "items": [
      {{ "number": 1, "title": "Concept clé", "description": "Description courte et actionnable." }},
      {{ "number": 2, "title": "Autre concept", "description": "Explication concise." }}
    ],
    "footer_cta": "Suivez-moi pour plus de conseils"
  }}
}}

{user_context}"""

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Transforme ce post LinkedIn en infographie de {num_items} éléments:\n\n{content}"}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
            if raw.endswith('```'):
                raw = raw[:-3].strip()

        data = json.loads(raw)
        infographic = data.get('infographic', data if isinstance(data, dict) and 'items' in data else {})

        return Response({
            'infographic': infographic,
            'metadata': {'tone': tone},
        })

    except json.JSONDecodeError:
        return Response({'error': 'Erreur de parsing. Réessayez.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        return Response({'error': 'Erreur API IA.'}, status=status.HTTP_502_BAD_GATEWAY)
    except Exception as e:
        logger.error(f"Convert to infographic error: {e}")
        return Response({'error': 'Erreur interne'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
def convert_to_post(request):
    """Convert carousel slides or infographic items into a text post."""
    slides = request.data.get('slides', [])
    infographic = request.data.get('infographic', {})
    tone = request.data.get('tone', 'professionnel')

    source = ''
    if slides:
        for slide in slides:
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
            source += ' — '.join(parts) + '\n'
    elif infographic:
        if infographic.get('title'):
            source += f"Titre: {infographic['title']}\n"
        if infographic.get('subtitle'):
            source += f"Sous-titre: {infographic['subtitle']}\n"
        for item in infographic.get('items', []):
            source += f"{item.get('number', '')}. {item.get('title', '')} — {item.get('description', '')}\n"

    if not source.strip():
        return Response({'error': 'Contenu source requis (slides ou infographic)'}, status=status.HTTP_400_BAD_REQUEST)

    if not settings.ANTHROPIC_API_KEY:
        return Response({'error': 'ANTHROPIC_API_KEY is not configured'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    user_context = get_user_context(request)

    system_prompt = f"""Tu es un ghostwriter LinkedIn d'élite.
Tu transformes le contenu structuré (carousel ou infographie) en un post LinkedIn texte viral.

RÈGLES:
- Hook percutant en première ligne (stoppe le scroll)
- Structure aérée avec phrases courtes
- Emojis avec parcimonie (2-4 max, jamais en début)
- 150-300 mots
- 3-5 hashtags à la fin
- Ton: {tone}
- NE COMMENCE JAMAIS par "🚀 Ravi de..." ou "Je suis heureux de..."
- Retourne UNIQUEMENT le post

{user_context}"""

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Transforme ce contenu en post LinkedIn:\n\n{source}"}],
        )

        generated = response.content[0].text.strip()
        body, hashtags = extract_hashtags(generated)

        return Response({
            'post': body,
            'hashtags': hashtags,
        })

    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        return Response({'error': 'Erreur API IA.'}, status=status.HTTP_502_BAD_GATEWAY)
    except Exception as e:
        logger.error(f"Convert to post error: {e}")
        return Response({'error': 'Erreur interne'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
