import re
import logging
import ipaddress
from urllib.parse import urlparse

import requests as http_requests
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
import anthropic

from .views import get_user_context

logger = logging.getLogger(__name__)


def is_safe_url(url):
    """Validate URL to prevent SSRF attacks against internal services."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        # Block common internal hostnames
        blocked_hosts = {'localhost', '127.0.0.1', '0.0.0.0', '::1', 'metadata.google.internal'}
        if hostname.lower() in blocked_hosts:
            return False
        # Block internal IP ranges
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        except ValueError:
            # hostname is a domain, not an IP — check for cloud metadata endpoints
            if hostname.endswith('.internal') or hostname.endswith('.local'):
                return False
        # Block non-http(s) schemes
        if parsed.scheme not in ('http', 'https'):
            return False
        return True
    except Exception:
        return False


def _strip_tags(html):
    """Strip HTML tags and extract readable text."""
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<br\s*/?\s*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</(?:p|div|li|h[1-6])>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    html = html.replace('&nbsp;', ' ').replace('&quot;', '"').replace('&#39;', "'")
    html = re.sub(r'[ \t]+', ' ', html)
    html = re.sub(r'\n\s*\n+', '\n\n', html)
    return html.strip()


def extract_article_content(html):
    """Try to extract content from <article> or <main> tags first, fall back to full page."""
    # Try <article> first (most blogs)
    article = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL | re.IGNORECASE)
    if article:
        return _strip_tags(article.group(1))
    # Try <main>
    main = re.search(r'<main[^>]*>(.*?)</main>', html, re.DOTALL | re.IGNORECASE)
    if main:
        return _strip_tags(main.group(1))
    # Try role="main"
    role_main = re.search(r'<div[^>]*role=["\']main["\'][^>]*>(.*?)</div>', html, re.DOTALL | re.IGNORECASE)
    if role_main:
        return _strip_tags(role_main.group(1))
    # Fallback to full page
    return _strip_tags(html)


def extract_meta(html):
    """Extract meta description and OG tags as fallback content."""
    parts = []
    # og:title
    m = re.search(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not m:
        m = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']', html, re.IGNORECASE)
    if m:
        parts.append(m.group(1).strip())
    # og:description
    m = re.search(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not m:
        m = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:description["\']', html, re.IGNORECASE)
    if m:
        parts.append(m.group(1).strip())
    # meta description
    m = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not m:
        m = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']description["\']', html, re.IGNORECASE)
    if m and m.group(1).strip() not in parts:
        parts.append(m.group(1).strip())
    return '\n'.join(parts)


def extract_title(html):
    """Extract <title> tag content."""
    match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ''


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def extract_url_content(request):
    """Extract and summarize content from a URL for repurposing."""
    url = request.data.get('url', '').strip()

    if not url:
        return Response({'error': 'URL requise'}, status=status.HTTP_400_BAD_REQUEST)

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    if not is_safe_url(url):
        return Response({'error': 'URL non autorisée'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        resp = http_requests.get(
            url,
            timeout=15,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
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

    # Try article/main content first, then full page
    text = extract_article_content(raw_html)
    text = text[:8000]

    # If article extraction yields little, supplement with meta tags
    if len(text) < 100:
        meta = extract_meta(raw_html)
        if meta:
            text = f"{meta}\n\n{text}".strip()[:8000]

    if len(text) < 50:
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
