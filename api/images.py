import base64
import requests

import anthropic
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
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
@permission_classes([IsAuthenticated])
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
@permission_classes([IsAuthenticated])
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

        full_prompt = f"{prompt}. IMPORTANT: Do not include any text, letters, words, watermarks or typography on the image."

        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[full_prompt],
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def generate_image_hf(request):
    """Génère une illustration via HuggingFace Inference API (FLUX.1-schnell)"""
    prompt = request.data.get('prompt', '').strip()

    if not prompt:
        return Response(
            {'error': 'Le prompt est requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not settings.HF_TOKEN:
        return Response(
            {'error': 'HF_TOKEN non configuré'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    try:
        full_prompt = (
            "cartoon minimalist illustration, clean vector style, "
            "no text no letters no words no watermark no typography: "
            f"{prompt}"
        )

        resp = requests.post(
            "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
            headers={"Authorization": f"Bearer {settings.HF_TOKEN}"},
            json={"inputs": full_prompt, "parameters": {"width": 1024, "height": 1024}},
            timeout=60,
        )

        if resp.status_code == 429:
            return Response(
                {'error': 'Limite de requêtes HuggingFace atteinte, réessayez plus tard'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        if resp.status_code == 503:
            return Response(
                {'error': 'Le modèle est en cours de chargement, réessayez dans quelques secondes'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        if resp.status_code != 200:
            return Response(
                {'error': f'Erreur HuggingFace: {resp.status_code}'},
                status=status.HTTP_502_BAD_GATEWAY
            )

        content_type = resp.headers.get('content-type', 'image/jpeg')
        image_base64 = base64.b64encode(resp.content).decode('utf-8')

        return Response({
            'image': image_base64,
            'mime_type': content_type,
        })

    except requests.Timeout:
        return Response(
            {'error': 'Délai de génération dépassé (60s)'},
            status=status.HTTP_504_GATEWAY_TIMEOUT
        )
    except Exception as e:
        return Response(
            {'error': f'Erreur génération illustration: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ---------------------------------------------------------------------------
# Reusable image generation (for autopilot etc.)
# ---------------------------------------------------------------------------

import logging
_img_logger = logging.getLogger(__name__)


def generate_image_for_post(post_content: str, topic: str = "") -> dict | None:
    """Find or generate an illustration for a post. Returns {'data': base64, 'mime_type': str} or None.

    Priority: Tavily image search (real photos) → Pexels → Gemini AI → HuggingFace Flux.
    """
    # Build a search query from the topic/content
    search_query = _build_image_search_query(post_content, topic)

    # 1. Try Tavily image search (preferred — real, relevant photos)
    if getattr(settings, 'TAVILY_API_KEY', None):
        result = _try_tavily_image(search_query)
        if result:
            _img_logger.info(f"Image from Tavily for: {search_query[:50]}")
            return result

    # 2. Fallback: Pexels
    if getattr(settings, 'PEXELS_API_KEY', None):
        result = _try_pexels_image(search_query)
        if result:
            _img_logger.info(f"Image from Pexels for: {search_query[:50]}")
            return result

    # 3. Fallback: Gemini AI generation
    prompt = _build_image_prompt(post_content, topic)
    if settings.GOOGLE_API_KEY:
        result = _try_gemini_image(prompt)
        if result:
            _img_logger.info(f"Image from Gemini AI for: {topic[:50]}")
            return result

    # 4. Last resort: HuggingFace Flux
    if getattr(settings, 'HF_TOKEN', None):
        result = _try_hf_image(prompt)
        if result:
            _img_logger.info(f"Image from HF Flux for: {topic[:50]}")
            return result

    _img_logger.warning("Image generation: all sources failed")
    return None


def _build_image_search_query(post_content: str, topic: str) -> str:
    """Build a short English search query for finding relevant photos."""
    # Use topic if available, otherwise first 100 chars of content
    base = topic if topic else post_content[:100].replace('\n', ' ').strip()

    # Use Claude to translate/adapt to a good English image search query
    try:
        import anthropic as _anth
        client = _anth.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            system=(
                "Convert the topic into a short English image search query (3-5 words) "
                "to find a professional, relevant photo. Return ONLY the query, nothing else."
            ),
            messages=[{"role": "user", "content": base}],
        )
        query = response.content[0].text.strip()
        if query:
            return query
    except Exception as e:
        _img_logger.warning(f"Search query generation failed: {e}")

    return base[:60]


def _try_tavily_image(query: str) -> dict | None:
    """Search for images via Tavily and download the best one as base64."""
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=3,
            include_images=True,
            include_answer=False,
        )

        images = response.get('images', [])
        if not images:
            return None

        # Try to download the first valid image
        for img_url in images[:3]:
            if not isinstance(img_url, str) or not img_url.startswith('http'):
                continue
            try:
                resp = requests.get(img_url, timeout=15, headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; PostFlow/1.0)'
                })
                if resp.status_code != 200:
                    continue
                content_type = resp.headers.get('content-type', '')
                if 'image' not in content_type:
                    continue
                mime = 'image/jpeg'
                if 'png' in content_type:
                    mime = 'image/png'
                elif 'webp' in content_type:
                    mime = 'image/webp'

                return {
                    'data': base64.b64encode(resp.content).decode('utf-8'),
                    'mime_type': mime,
                }
            except Exception:
                continue

    except Exception as e:
        _img_logger.warning(f"Tavily image search failed: {e}")

    return None


def _try_pexels_image(query: str) -> dict | None:
    """Search for images via Pexels and download the best one as base64."""
    try:
        headers = {'Authorization': settings.PEXELS_API_KEY}
        resp = requests.get(
            'https://api.pexels.com/v1/search',
            params={'query': query, 'per_page': 3, 'orientation': 'square'},
            headers=headers,
            timeout=10,
        )

        if resp.status_code != 200:
            return None

        photos = resp.json().get('photos', [])
        if not photos:
            return None

        # Download the first photo (large size — good quality for LinkedIn)
        img_url = photos[0]['src']['large']
        img_resp = requests.get(img_url, timeout=15)
        if img_resp.status_code != 200:
            return None

        content_type = img_resp.headers.get('content-type', 'image/jpeg')
        mime = 'image/jpeg'
        if 'png' in content_type:
            mime = 'image/png'

        return {
            'data': base64.b64encode(img_resp.content).decode('utf-8'),
            'mime_type': mime,
        }

    except Exception as e:
        _img_logger.warning(f"Pexels image search failed: {e}")

    return None


def _build_image_prompt(post_content: str, topic: str) -> str:
    """Build a concise image prompt from post content."""
    # Take first 150 chars of content as context
    snippet = post_content[:150].replace('\n', ' ').strip()
    base = topic if topic else snippet

    return (
        f"Professional LinkedIn post illustration about: {base}. "
        "Modern, clean, minimalist style. Corporate/business aesthetic. "
        "Subtle gradient background. No text, no letters, no words, no watermark."
    )


def _try_gemini_image(prompt: str) -> dict | None:
    """Try generating image via Gemini."""
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

        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith('image/'):
                return {
                    'data': base64.b64encode(part.inline_data.data).decode('utf-8'),
                    'mime_type': part.inline_data.mime_type,
                }

    except Exception as e:
        _img_logger.warning(f"Gemini image failed: {e}")

    return None


def _try_hf_image(prompt: str) -> dict | None:
    """Try generating image via HuggingFace Flux."""
    try:
        full_prompt = (
            "clean professional illustration, modern flat design, "
            "no text no letters no words no watermark: "
            f"{prompt}"
        )

        resp = requests.post(
            "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
            headers={"Authorization": f"Bearer {settings.HF_TOKEN}"},
            json={"inputs": full_prompt, "parameters": {"width": 1024, "height": 1024}},
            timeout=60,
        )

        if resp.status_code != 200:
            _img_logger.warning(f"HF image failed: status {resp.status_code}")
            return None

        content_type = resp.headers.get('content-type', 'image/jpeg')
        return {
            'data': base64.b64encode(resp.content).decode('utf-8'),
            'mime_type': content_type,
        }

    except Exception as e:
        _img_logger.warning(f"HF image failed: {e}")

    return None
