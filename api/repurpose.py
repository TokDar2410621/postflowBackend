import re
import logging

import requests as http_requests
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
import anthropic

from .views import get_user_context

logger = logging.getLogger(__name__)


def strip_html(html):
    """Strip HTML tags and extract readable text."""
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<br\s*/?\s*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</(?:p|div|li|h[1-6])>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    html = html.replace('&nbsp;', ' ').replace('&quot;', '"').replace('&#39;', "'")
    html = re.sub(r'[ \t]+', ' ', html)
    html = re.sub(r'\n\s*\n+', '\n\n', html)
    return html.strip()


def extract_title(html):
    """Extract <title> tag content."""
    match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ''


@api_view(['POST'])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
def extract_url_content(request):
    """Extract and summarize content from a URL for repurposing."""
    url = request.data.get('url', '').strip()

    if not url:
        return Response({'error': 'URL requise'}, status=status.HTTP_400_BAD_REQUEST)

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        resp = http_requests.get(
            url,
            timeout=15,
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; PostFlow/1.0)',
                'Accept': 'text/html,application/xhtml+xml',
            },
            allow_redirects=True,
        )
        resp.raise_for_status()
    except http_requests.RequestException as e:
        logger.error(f"URL fetch error: {e}")
        return Response(
            {'error': f"Impossible d'accéder à l'URL"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    raw_html = resp.text
    title = extract_title(raw_html)
    text = strip_html(raw_html)
    text = text[:8000]

    if len(text) < 100:
        return Response(
            {'error': "Contenu insuffisant extrait de l'URL"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not settings.ANTHROPIC_API_KEY:
        return Response(
            {'error': 'ANTHROPIC_API_KEY is not configured'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        user_context = get_user_context(request)

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=f"""Tu es un expert en analyse de contenu. Extrais et résume le contenu principal de cette page web.

RÈGLES:
- Identifie le sujet principal, les points clés, les données importantes
- Ignore la navigation, les pubs, les footers, les sidebars
- Résume en 200-400 mots en français
- Structure avec des paragraphes clairs
- Conserve les chiffres, citations et données factuelles importants
- Le résumé servira de base pour créer du contenu LinkedIn

{user_context}""",
            messages=[
                {"role": "user", "content": f"Titre de la page : {title}\n\nContenu extrait :\n{text}"}
            ],
        )

        extracted = message.content[0].text.strip()

        return Response({
            'extracted_content': extracted,
            'source_url': url,
            'title': title,
        })

    except anthropic.APIError as e:
        logger.error(f"Anthropic API error (extract): {e}")
        return Response(
            {'error': 'Erreur API IA. Réessayez.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as e:
        logger.error(f"Extract content error: {e}")
        return Response(
            {'error': 'Erreur interne'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
