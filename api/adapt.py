"""
Adapt a post from one platform to another.
Takes existing content and rewrites it for the target platform's format and rules.
"""
import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import GeneratedPost, PLATFORM_CHOICES
from .llm import resolve_model, generate_text
from .prompts import _PLATFORMS
from .views import extract_hashtags, get_user_context

logger = logging.getLogger(__name__)

VALID_PLATFORMS = {p[0] for p in PLATFORM_CHOICES}


def _build_adapt_prompt(source_platform, target_platform, user_context=None):
    """Build system prompt for adapting content between platforms."""
    source = _PLATFORMS.get(source_platform, _PLATFORMS['linkedin'])
    target = _PLATFORMS.get(target_platform, _PLATFORMS['linkedin'])

    prompt = f"""Tu es un expert en création de contenu multi-plateforme.

Ta mission : adapter un post {source['name']} pour {target['name']}.

RÈGLES IMPORTANTES :
- Garde le MÊME message, la MÊME idée centrale, le MÊME ton de voix
- Adapte UNIQUEMENT le format, la longueur et le style pour {target['name']}
- Ne change PAS le fond du message, seulement la forme
- Le résultat doit sembler natif sur {target['name']}, pas un copier-coller

{target['hook']}

{target['format']}

Retourne UNIQUEMENT le post adapté, sans commentaire ni explication."""

    if user_context:
        prompt += f"\n\nContexte de l'auteur :\n{user_context}"

    return prompt


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def adapt_post(request):
    """
    Adapt a post from one platform to another.
    POST /api/adapt/
    Body: { content: str, source_platform: str, target_platform: str }
    """
    content = request.data.get('content', '').strip()
    source_platform = request.data.get('source_platform', 'linkedin')
    target_platform = request.data.get('target_platform', '')
    model = request.data.get('model')

    if not content:
        return Response({'error': 'Contenu requis'}, status=status.HTTP_400_BAD_REQUEST)

    if target_platform not in VALID_PLATFORMS:
        return Response({'error': f'Plateforme cible invalide: {target_platform}'}, status=status.HTTP_400_BAD_REQUEST)

    if source_platform == target_platform:
        return Response({'error': 'Les plateformes source et cible doivent être différentes'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        model_id = resolve_model(request.user, model)
        user_context = get_user_context(request)
        system_prompt = _build_adapt_prompt(source_platform, target_platform, user_context)

        user_message = f"Voici le post {_PLATFORMS.get(source_platform, {}).get('name', source_platform)} à adapter pour {_PLATFORMS.get(target_platform, {}).get('name', target_platform)} :\n\n{content}"

        adapted_content = generate_text(
            model_id=model_id,
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=1024,
        )

        body, hashtags = extract_hashtags(adapted_content)

        # Save as new post
        post = GeneratedPost.objects.create(
            user=request.user,
            summary=f"[Adapté de {source_platform}] {content[:200]}",
            tone='professionnel',
            platform=target_platform,
            generated_content=adapted_content,
        )

        return Response({
            'post': body,
            'hashtags': hashtags,
            'id': post.id,
            'platform': target_platform,
            'source_platform': source_platform,
        })

    except Exception as e:
        logger.error(f"Adapt post error: {e}", exc_info=True)
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
