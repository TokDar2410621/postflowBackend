"""
Web search module for fact-checking and context enrichment.

Flow:
1. Extract specific entities/tools/products from user's summary (via Claude Haiku)
2. Search the web for each entity (via Tavily)
3. Return verified context to inject into generation prompts
"""
import json
import logging

from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
import anthropic

logger = logging.getLogger(__name__)


def extract_entities(text: str) -> list[str]:
    """
    Use a fast LLM call to extract specific entities that need web verification.
    Returns a list of search queries (empty if nothing needs checking).
    """
    api_key = getattr(settings, 'ANTHROPIC_API_KEY', '')
    if not api_key or not text.strip():
        return []

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system="""Tu es un analyseur de texte. Ton rôle est d'identifier les entités spécifiques
qui nécessitent une vérification factuelle sur le web.

Extrais UNIQUEMENT les entités suivantes si elles sont présentes :
- Noms de produits, outils, logiciels, apps (ex: "NanoBanana", "Notion", "Figma")
- Noms d'entreprises ou startups peu connues
- Événements récents ou actualités spécifiques
- Statistiques ou chiffres cités sans source
- Concepts techniques ou méthodologies spécifiques et récentes

NE PAS extraire :
- Des concepts généraux bien connus (management, marketing, leadership, IA en général)
- Des noms de grandes entreprises très connues (Google, Apple, Microsoft)
- Des conseils génériques ("5 astuces pour...")

Retourne un JSON strict : {"entities": ["query1", "query2"]}
Si rien ne nécessite de vérification, retourne : {"entities": []}""",
            messages=[{"role": "user", "content": text}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
            if raw.endswith('```'):
                raw = raw[:-3].strip()

        data = json.loads(raw)
        entities = data.get('entities', [])

        # Limit to 3 searches max to control costs
        return entities[:3]

    except Exception as e:
        logger.warning(f"Entity extraction failed: {e}")
        return []


def search_web(queries: list[str]) -> list[dict]:
    """
    Search the web using Tavily for each query.
    Returns a list of search results with title, url, and content.
    """
    api_key = getattr(settings, 'TAVILY_API_KEY', '')
    if not api_key or not queries:
        return []

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
    except Exception as e:
        logger.warning(f"Tavily client init failed: {e}")
        return []

    all_results = []

    for query in queries:
        try:
            response = client.search(
                query=query,
                search_depth="basic",
                max_results=3,
                include_answer=True,
            )

            # Collect the AI-generated answer if available
            if response.get('answer'):
                all_results.append({
                    'query': query,
                    'answer': response['answer'],
                    'sources': [
                        {'title': r.get('title', ''), 'url': r.get('url', '')}
                        for r in response.get('results', [])[:3]
                    ],
                })
            elif response.get('results'):
                # Fallback: use raw results
                top = response['results'][0]
                all_results.append({
                    'query': query,
                    'answer': top.get('content', ''),
                    'sources': [
                        {'title': r.get('title', ''), 'url': r.get('url', '')}
                        for r in response.get('results', [])[:3]
                    ],
                })

        except Exception as e:
            logger.warning(f"Tavily search failed for '{query}': {e}")
            continue

    return all_results


def enrich_context(text: str) -> str:
    """
    Main entry point. Takes user's summary/topic, extracts entities,
    searches the web, and returns a context block to inject into prompts.

    Returns empty string if no enrichment needed or if search fails.
    """
    # Step 1: Extract entities that need verification
    entities = extract_entities(text)

    if not entities:
        return ""

    logger.info(f"Web search: checking entities {entities}")

    # Step 2: Search the web
    results = search_web(entities)

    if not results:
        return ""

    # Step 3: Format as context block
    lines = ["CONTEXTE VÉRIFIÉ PAR RECHERCHE WEB (utilise ces informations comme source de vérité) :"]

    for r in results:
        lines.append(f"\n• {r['query']} :")
        lines.append(f"  {r['answer']}")
        if r.get('sources'):
            source_names = [s['title'] for s in r['sources'] if s['title']]
            if source_names:
                lines.append(f"  Sources : {', '.join(source_names[:2])}")

    context = '\n'.join(lines)

    # Cap at ~2000 chars to limit token usage
    if len(context) > 2000:
        context = context[:2000] + "\n..."

    return context


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def web_search(request):
    """
    Manual web search endpoint.
    POST /api/web/search/ with {"query": "..."}
    Returns search results the user can use to generate posts.
    """
    query = request.data.get('query', '').strip()
    if not query:
        return Response(
            {'error': 'Le champ query est requis'},
            status=http_status.HTTP_400_BAD_REQUEST,
        )

    if len(query) > 500:
        return Response(
            {'error': 'La requête est trop longue (max 500 caractères)'},
            status=http_status.HTTP_400_BAD_REQUEST,
        )

    results = search_web([query])

    if not results:
        return Response(
            {'error': 'Aucun résultat trouvé. Vérifiez votre requête.'},
            status=http_status.HTTP_404_NOT_FOUND,
        )

    # Return richer results for the frontend
    api_key = getattr(settings, 'TAVILY_API_KEY', '')
    if not api_key:
        return Response(
            {'error': 'Recherche web non configurée'},
            status=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=8,
            include_answer=True,
            include_images=True,
        )

        formatted_results = []
        for r in response.get('results', []):
            formatted_results.append({
                'title': r.get('title', ''),
                'url': r.get('url', ''),
                'content': r.get('content', ''),
                'score': r.get('score', 0),
            })

        return Response({
            'query': query,
            'answer': response.get('answer', ''),
            'results': formatted_results,
            'images': response.get('images', []),
        })

    except Exception as e:
        logger.error(f"Web search endpoint error: {e}")
        return Response(
            {'error': 'Erreur lors de la recherche web'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def web_image_search(request):
    """
    Search for images on the web.
    POST /api/web/images/ with {"query": "..."}
    Returns image URLs from the web.
    """
    query = request.data.get('query', '').strip()
    if not query:
        return Response(
            {'error': 'Le champ query est requis'},
            status=http_status.HTTP_400_BAD_REQUEST,
        )

    api_key = getattr(settings, 'TAVILY_API_KEY', '')
    if not api_key:
        return Response(
            {'error': 'Recherche web non configurée'},
            status=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_images=True,
            include_answer=False,
        )

        images = response.get('images', [])

        return Response({
            'query': query,
            'images': images,
        })

    except Exception as e:
        logger.error(f"Web image search error: {e}")
        return Response(
            {'error': 'Erreur lors de la recherche d\'images'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
