import json
import logging
from urllib.parse import quote

import anthropic
import requests
from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import LinkedInAccount, PublishedPost
from .views import get_user_context

logger = logging.getLogger(__name__)

LINKEDIN_API_VERSION = "202506"
LINKEDIN_SOCIAL_ACTIONS_URL = "https://api.linkedin.com/rest/socialActions"


def _get_linkedin_account(request):
    """Return (account, error_response). If error_response is not None, return it."""
    account = LinkedInAccount.objects.filter(user=request.user).first()
    if not account:
        return None, Response(
            {'error': 'Aucun compte LinkedIn connecté'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if account.is_expired:
        return None, Response(
            {'error': 'Token LinkedIn expiré, reconnectez-vous'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    return account, None


def _linkedin_headers(account):
    return {
        'Authorization': f'Bearer {account.access_token}',
        'LinkedIn-Version': LINKEDIN_API_VERSION,
        'X-Restli-Protocol-Version': '2.0.0',
    }


# ─── Endpoint 1 : Fetch comments from LinkedIn ───────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def fetch_comments(request, post_id):
    """Récupère les commentaires LinkedIn d'un post publié."""
    try:
        post = PublishedPost.objects.get(pk=post_id, user=request.user)
    except PublishedPost.DoesNotExist:
        return Response({'error': 'Post non trouvé'}, status=status.HTTP_404_NOT_FOUND)

    if not post.linkedin_post_id:
        return Response(
            {'error': "Ce post n'a pas d'identifiant LinkedIn"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    account, err = _get_linkedin_account(request)
    if err:
        return err

    # Check cache (5 min TTL)
    cache_key = f'comments:{post.linkedin_post_id}'
    cached = cache.get(cache_key)
    if cached is not None:
        return Response({
            'post_id': post.id,
            'linkedin_post_id': post.linkedin_post_id,
            'post_content': post.content,
            'comments': cached,
            'cached': True,
        })

    # Call LinkedIn socialActions API
    encoded_urn = quote(post.linkedin_post_id, safe='')
    headers = _linkedin_headers(account)

    try:
        resp = requests.get(
            f'{LINKEDIN_SOCIAL_ACTIONS_URL}/{encoded_urn}/comments'
            '?count=50&sortOrder=REVERSE_CHRONOLOGICAL',
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as e:
        logger.error(f"LinkedIn comments API error: {e}")
        return Response(
            {'error': 'Erreur de connexion à LinkedIn'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if resp.status_code != 200:
        logger.error(f"LinkedIn comments API {resp.status_code}: {resp.text[:500]}")
        return Response(
            {'error': f'Erreur LinkedIn ({resp.status_code})'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # Parse response
    data = resp.json()
    elements = data.get('elements', [])

    comments = []
    for elem in elements:
        comment_urn = elem.get('$URN', elem.get('commentUrn', ''))
        actor = elem.get('actor', '')
        message = elem.get('message', {})
        comment_text = message.get('text', '') if isinstance(message, dict) else str(message)
        created_at = elem.get('created', {}).get('time', 0)
        likes_count = elem.get('likesSummary', {}).get('totalLikes', 0)

        # Author info (may be restricted by LinkedIn privacy)
        author_name = ''
        if 'actor~' in elem:
            actor_details = elem['actor~']
            first = actor_details.get('firstName', '')
            last = actor_details.get('lastName', '')
            author_name = f'{first} {last}'.strip()

        comments.append({
            'comment_urn': comment_urn,
            'actor_urn': actor,
            'author_name': author_name or 'Utilisateur LinkedIn',
            'author_image': '',
            'text': comment_text,
            'created_at': created_at,
            'likes': likes_count,
        })

    # Cache for 5 minutes
    cache.set(cache_key, comments, timeout=300)

    return Response({
        'post_id': post.id,
        'linkedin_post_id': post.linkedin_post_id,
        'post_content': post.content,
        'comments': comments,
        'cached': False,
    })


# ─── Endpoint 2 : Analyze sentiment + suggest replies ────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def analyze_comments(request):
    """Analyse le sentiment des commentaires et suggère des réponses via Claude."""
    post_id = request.data.get('post_id')
    comments = request.data.get('comments', [])
    post_content = request.data.get('post_content', '')

    if not comments:
        return Response(
            {'error': 'Aucun commentaire à analyser'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not settings.ANTHROPIC_API_KEY:
        return Response(
            {'error': 'ANTHROPIC_API_KEY is not configured'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Build comments block (max 30)
    comments_block = ''
    for i, c in enumerate(comments[:30]):
        author = c.get('author_name', 'Inconnu')
        text = c.get('text', '')
        comments_block += f'\n[{i}] {author}: {text}'

    user_context = get_user_context(request)

    system_prompt = f"""Tu es un expert en community management LinkedIn.
Tu analyses des commentaires sous un post LinkedIn et tu proposes des réponses personnalisées.

Pour CHAQUE commentaire, tu dois :
1. Classifier le sentiment : "positive", "neutral", "negative", ou "question"
2. Générer une réponse suggérée, courte (1-3 phrases), authentique et engageante

Règles pour les réponses :
- Mentionne le prénom de l'auteur si disponible (pas "Utilisateur LinkedIn")
- Sois reconnaissant pour les commentaires positifs
- Réponds de manière constructive aux commentaires négatifs
- Donne une réponse utile aux questions
- Reste neutre mais engageant pour les commentaires neutres
- Adapte le ton au style de l'auteur du post
- N'utilise PAS d'emojis excessifs, reste professionnel

{user_context}

IMPORTANT : Réponds en JSON valide, un tableau d'objets avec les champs :
- index (int) : l'index du commentaire
- sentiment (string) : "positive" | "neutral" | "negative" | "question"
- suggested_reply (string) : la réponse suggérée

Retourne UNIQUEMENT le JSON, sans markdown, sans backticks, sans explication."""

    user_prompt = f"""POST ORIGINAL :
{post_content}

COMMENTAIRES :
{comments_block}"""

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text.strip()

        # Handle markdown wrapping
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
            if raw.endswith('```'):
                raw = raw[:-3]
            raw = raw.strip()

        analyses = json.loads(raw)

        # Merge analysis into comments
        analysis_map = {a['index']: a for a in analyses}
        enriched = []
        for i, c in enumerate(comments[:30]):
            analysis = analysis_map.get(i, {})
            enriched.append({
                **c,
                'sentiment': analysis.get('sentiment', 'neutral'),
                'suggested_reply': analysis.get('suggested_reply', ''),
            })

        return Response({
            'post_id': post_id,
            'analyzed_comments': enriched,
        })

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error from Claude: {e}")
        return Response(
            {"error": "Erreur d'analyse IA (format invalide)"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    except anthropic.RateLimitError:
        return Response(
            {'error': 'Trop de requêtes, réessayez dans un moment.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    except anthropic.AuthenticationError:
        return Response(
            {'error': 'Clé API Anthropic invalide ou expirée.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    except Exception as e:
        logger.error(f"Comment analysis error: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ─── Endpoint 3 : Reply to a comment on LinkedIn ─────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reply_to_comment(request):
    """Publie une réponse à un commentaire sur LinkedIn."""
    post_urn = request.data.get('post_urn', '').strip()
    comment_urn = request.data.get('comment_urn', '').strip()
    reply_text = request.data.get('reply_text', '').strip()

    if not post_urn or not reply_text:
        return Response(
            {'error': 'post_urn et reply_text sont requis'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    account, err = _get_linkedin_account(request)
    if err:
        return err

    encoded_urn = quote(post_urn, safe='')
    headers = {
        **_linkedin_headers(account),
        'Content-Type': 'application/json',
    }

    body = {
        'actor': f'urn:li:person:{account.linkedin_id}',
        'message': {
            'text': reply_text,
        },
    }

    if comment_urn:
        body['parentComment'] = comment_urn

    try:
        resp = requests.post(
            f'{LINKEDIN_SOCIAL_ACTIONS_URL}/{encoded_urn}/comments',
            json=body,
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as e:
        logger.error(f"LinkedIn reply API error: {e}")
        return Response(
            {'error': 'Erreur de connexion à LinkedIn'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if resp.status_code in [200, 201]:
        # Invalidate cached comments
        cache.delete(f'comments:{post_urn}')
        return Response({
            'success': True,
            'message': 'Réponse publiée avec succès !',
        })

    error_detail = resp.text[:500]
    logger.error(f"LinkedIn reply failed: {resp.status_code} {error_detail}")
    return Response(
        {'error': f'Erreur LinkedIn: {error_detail}'},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
