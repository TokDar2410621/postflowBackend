import base64
import requests

import anthropic
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import JSONParser
from rest_framework.response import Response


@api_view(['GET'])
def search_images(request):
    """Recherche d'images sur Pexels (proxy pour garder la clé API côté serveur)"""
    query = request.GET.get('query', '').strip()
    page = int(request.GET.get('page', 1))
    per_page = min(int(request.GET.get('per_page', 15)), 30)

    if not query:
        return Response(
            {'error': 'Le paramètre "query" est requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not settings.PEXELS_API_KEY:
        return Response(
            {'error': 'PEXELS_API_KEY non configurée'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    try:
        headers = {'Authorization': settings.PEXELS_API_KEY}
        resp = requests.get(
            'https://api.pexels.com/v1/search',
            params={'query': query, 'page': page, 'per_page': per_page, 'locale': 'fr-FR'},
            headers=headers,
            timeout=10
        )

        if resp.status_code == 429:
            return Response(
                {'error': 'Limite de requêtes Pexels atteinte, réessayez plus tard'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        if resp.status_code != 200:
            return Response(
                {'error': f'Erreur Pexels: {resp.status_code}'},
                status=status.HTTP_502_BAD_GATEWAY
            )

        data = resp.json()

        photos = []
        for photo in data.get('photos', []):
            photos.append({
                'id': photo['id'],
                'width': photo['width'],
                'height': photo['height'],
                'photographer': photo['photographer'],
                'photographer_url': photo['photographer_url'],
                'alt': photo.get('alt', ''),
                'src': {
                    'original': photo['src']['original'],
                    'large': photo['src']['large'],
                    'medium': photo['src']['medium'],
                    'small': photo['src']['small'],
                    'tiny': photo['src']['tiny'],
                }
            })

        return Response({
            'photos': photos,
            'total_results': data.get('total_results', 0),
            'page': page,
            'per_page': per_page,
        })

    except requests.Timeout:
        return Response(
            {'error': 'Délai de requête Pexels dépassé'},
            status=status.HTTP_504_GATEWAY_TIMEOUT
        )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@parser_classes([JSONParser])
def suggest_image_keywords(request):
    """Suggère des mots-clés de recherche d'image basés sur le contenu du post"""
    content = request.data.get('content', '').strip()

    if not content:
        return Response(
            {'error': 'Le contenu du post est requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=128,
            system=(
                "Tu es un assistant qui suggère des mots-clés de recherche d'images. "
                "A partir du post LinkedIn fourni, suggère 5 mots-clés courts (1-3 mots chacun) en anglais "
                "pour trouver une image illustrative pertinente sur une banque d'images. "
                "Retourne UNIQUEMENT les mots-clés, un par ligne, sans numérotation ni ponctuation."
            ),
            messages=[{"role": "user", "content": content}]
        )

        raw = message.content[0].text
        keywords = [kw.strip() for kw in raw.split('\n') if kw.strip()]

        return Response({'keywords': keywords[:5]})

    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@parser_classes([JSONParser])
def generate_image(request):
    """Génère une image avec Gemini à partir d'un prompt"""
    prompt = request.data.get('prompt', '').strip()

    if not prompt:
        return Response(
            {'error': 'Le prompt est requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not settings.GOOGLE_API_KEY:
        return Response(
            {'error': 'GOOGLE_API_KEY non configurée'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.GOOGLE_API_KEY)

        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            )
        )

        # Extraire l'image de la réponse
        image_part = None
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith('image/'):
                image_part = part
                break

        if not image_part:
            return Response(
                {'error': 'Aucune image générée par le modèle'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        image_base64 = base64.b64encode(image_part.inline_data.data).decode('utf-8')

        return Response({
            'image': image_base64,
            'mime_type': image_part.inline_data.mime_type,
        })

    except Exception as e:
        error_msg = str(e)
        if 'RESOURCE_EXHAUSTED' in error_msg or 'quota' in error_msg.lower():
            return Response(
                {'error': 'Quota Gemini épuisé. Activez la facturation sur Google AI Studio ou réessayez plus tard.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        return Response(
            {'error': f'Erreur génération image: {error_msg}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
