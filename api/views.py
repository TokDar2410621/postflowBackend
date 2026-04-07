import re
import base64
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
import anthropic

from .models import GeneratedPost, PublishedPost, PromptTemplate, UserProfile, SavedDraft
from .serializers import GeneratePostSerializer, GeneratedPostSerializer
from .billing import check_generation_limit, increment_usage
from .llm import get_user_plan, resolve_model, validate_model_access, generate_text
from .websearch import enrich_context
from .prompts import build_system_prompt, build_variants_system_prompt, build_single_variant_prompt, VALID_OBJECTIVES, VALID_PLATFORMS, VALID_TONES

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
MAX_IMAGES = 5
MAX_PROMPT_LENGTH = 5000  # Max characters for user text inputs


def validate_uploaded_images(images):
    """Valide les images uploadées (taille et type MIME). Retourne un message d'erreur ou None."""
    if len(images) > MAX_IMAGES:
        return f'Maximum {MAX_IMAGES} images autorisées'
    for img in images:
        content_type = getattr(img, 'content_type', '')
        if content_type not in ALLOWED_IMAGE_TYPES:
            return f'Type de fichier non autorisé: {content_type}. Types acceptés: JPEG, PNG, GIF, WebP'
        if img.size > MAX_IMAGE_SIZE:
            return f'Image trop volumineuse ({img.size // (1024*1024)}MB). Maximum: {MAX_IMAGE_SIZE // (1024*1024)}MB'
    return None


def get_user_context(request):
    """Récupère le contexte du profil utilisateur pour injection dans le prompt."""
    if not request.user.is_authenticated:
        return None
    try:
        profile = UserProfile.objects.get(user=request.user)
        ctx = profile.build_prompt_context()
        return ctx if ctx else None
    except UserProfile.DoesNotExist:
        return None


def get_objective(request):
    """Resolve the content objective from the request."""
    mode = request.data.get('mode')
    if mode in VALID_OBJECTIVES:
        return mode
    return 'audience_growth'


def get_platform(request):
    """Resolve the target platform from the request."""
    platform = request.data.get('platform')
    if platform in VALID_PLATFORMS:
        return platform
    return 'linkedin'


def extract_hashtags(content):
    """Extrait les hashtags de la fin du post et retourne (body, hashtags)"""
    hashtags = re.findall(r'#\w+', content)
    if not hashtags:
        return content, []

    # Trouver où les hashtags commencent (dernières lignes)
    lines = content.rstrip().split('\n')
    clean_lines = []
    for line in reversed(lines):
        words = line.strip().split()
        hashtag_words = [w for w in words if w.startswith('#')]
        if hashtag_words and len(hashtag_words) >= len(words) * 0.5:
            continue  # Ligne de hashtags, on la retire
        else:
            clean_lines.insert(0, line)

    body = '\n'.join(clean_lines).rstrip()
    return body, hashtags


def encode_image_to_base64(image_file):
    """Encode une image en base64 pour Claude Vision"""
    image_data = image_file.read()
    return base64.standard_b64encode(image_data).decode('utf-8')


def get_image_media_type(image_file):
    """Retourne le media type de l'image"""
    content_type = getattr(image_file, 'content_type', 'image/png')
    if content_type in ['image/jpeg', 'image/png', 'image/gif', 'image/webp']:
        return content_type
    # Fallback basé sur l'extension
    name = getattr(image_file, 'name', '').lower()
    if name.endswith('.jpg') or name.endswith('.jpeg'):
        return 'image/jpeg'
    elif name.endswith('.png'):
        return 'image/png'
    elif name.endswith('.gif'):
        return 'image/gif'
    elif name.endswith('.webp'):
        return 'image/webp'
    return 'image/png'


def analyze_images_with_vision(client, images):
    """Analyse les images avec Claude Vision et extrait le contexte"""
    if not images:
        return None

    # Construire le contenu avec les images
    content = []

    for image in images[:5]:  # Limiter à 5 images max
        image_data = encode_image_to_base64(image)
        media_type = get_image_media_type(image)

        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_data,
            }
        })

    content.append({
        "type": "text",
        "text": """Analyse ces images en détail. Extrait :
1. Le sujet principal (de quoi parle l'image)
2. Les informations clés visibles (texte, données, graphiques, code, interface, etc.)
3. Le contexte professionnel apparent
4. Les éléments qui pourraient être intéressants à partager sur LinkedIn

Fournis une synthèse concise mais complète qui servira de base pour créer un post LinkedIn engageant.
Réponds en français."""
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": content}
        ]
    )

    return response.content[0].text


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_reel_script(request):
    """Generate a Facebook Reel script (hook/body/cta)"""
    import json as json_module
    from .prompts import build_reel_script_prompt

    topic = request.data.get('topic', '').strip()
    tone = request.data.get('tone', 'humor')
    post_target = request.data.get('post_target', 'page')
    model = request.data.get('model')

    if not topic:
        return Response({'error': 'Le sujet est requis'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        model_id = resolve_model(request.user, model)
        user_context = get_user_context(request)
        system_prompt = build_reel_script_prompt(tone, post_target, user_context)

        user_message = f"Sujet du Reel : {topic}"

        raw = generate_text(
            model_id=model_id,
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=512,
        )

        # Parse JSON from response
        try:
            # Try to extract JSON from potential markdown code blocks
            cleaned = raw.strip()
            if '```' in cleaned:
                cleaned = cleaned.split('```json')[-1].split('```')[0].strip() if '```json' in cleaned else cleaned.split('```')[1].split('```')[0].strip()
            result = json_module.loads(cleaned)
        except (json_module.JSONDecodeError, IndexError):
            # Fallback: try to find JSON in the response
            import re
            match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
            if match:
                result = json_module.loads(match.group())
            else:
                return Response({'error': 'Impossible de parser le script genere'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'hook': result.get('hook', ''),
            'body': result.get('body', ''),
            'cta': result.get('cta', ''),
        })

    except Exception as e:
        logger.error(f"Reel script generation error: {e}", exc_info=True)
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def generate_post(request):
    """Génère un post LinkedIn à partir d'un résumé et/ou d'images"""

    # Vérifier la limite de générations
    can_generate, error_response = check_generation_limit(request.user)
    if not can_generate:
        return error_response

    # Récupérer les données
    summary = request.data.get('summary', '')
    tone = request.data.get('tone', 'professionnel')
    images = request.FILES.getlist('images')

    if images:
        img_error = validate_uploaded_images(images)
        if img_error:
            return Response({'error': img_error}, status=status.HTTP_400_BAD_REQUEST)

    # Template support
    template_id = request.data.get('template_id')
    template = None
    if template_id:
        try:
            template = PromptTemplate.objects.get(pk=int(template_id))
            if template.default_tone:
                tone = template.default_tone
        except (PromptTemplate.DoesNotExist, ValueError):
            pass

    # Validation du tone
    if tone not in VALID_TONES:
        tone = 'professionnel'

    # Vérifier la longueur du résumé
    if len(summary) > MAX_PROMPT_LENGTH:
        return Response(
            {'error': f'Le résumé est trop long ({len(summary)} caractères). Maximum: {MAX_PROMPT_LENGTH}.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Vérifier qu'on a au moins un résumé ou des images
    if not summary.strip() and not images:
        return Response(
            {'error': 'Veuillez fournir un résumé ou des images à analyser'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Résoudre et valider le modèle IA
    requested_model = request.data.get('model')
    user_plan = get_user_plan(request.user)
    model_id = resolve_model(requested_model, user_plan)
    is_allowed, model_error = validate_model_access(model_id, user_plan)
    if not is_allowed:
        return Response({'error': model_error}, status=status.HTTP_403_FORBIDDEN)

    try:
        # Étape 1: Analyser les images si présentes (toujours via Claude)
        image_context = None
        if images:
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            image_context = analyze_images_with_vision(client, images)

        # Construire le contexte final
        if image_context and summary.strip():
            full_context = f"""Contexte extrait des images :
{image_context}

Résumé additionnel fourni par l'utilisateur :
{summary}"""
        elif image_context:
            full_context = f"""Contexte extrait des images :
{image_context}"""
        else:
            full_context = summary

        # Appliquer le template prefix/suffix
        if template:
            prefix = template.prompt_prefix.strip()
            suffix = template.prompt_suffix.strip()
            if prefix:
                full_context = f"{prefix}\n\n{full_context}"
            if suffix:
                full_context = f"{full_context}\n\n{suffix}"

        # Étape 2: Enrichir avec recherche web si nécessaire
        web_context = enrich_context(full_context)

        # Étape 3: Générer le post
        objective = get_objective(request)
        platform = get_platform(request)
        use_profile = str(request.data.get('use_profile', 'true')).lower() != 'false'
        user_context = get_user_context(request)
        system_prompt = build_system_prompt(objective, tone, platform=platform, profile=user_context, web_context=web_context, use_profile=use_profile)

        user_message = f"Voici le contexte à transformer en post LinkedIn :\n\n{full_context}"
        if web_context:
            user_message += f"\n\n---\n{web_context}"

        generated_content = generate_text(
            model_id=model_id,
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=1024,
        )

        # Extraire les hashtags du post
        body, hashtags = extract_hashtags(generated_content)

        # Sauvegarder en base de données (contenu complet avec hashtags)
        post = GeneratedPost.objects.create(
            user=request.user,
            summary=summary if summary.strip() else (image_context[:500] if image_context else ''),
            tone=tone,
            platform=platform,
            generated_content=generated_content
        )

        increment_usage(request.user)

        return Response({
            'post': body,
            'hashtags': hashtags,
            'id': post.id,
            'image_analysis': image_context
        })

    except Exception as e:
        error_msg = str(e)
        if 'rate' in error_msg.lower() or '429' in error_msg:
            return Response({'error': 'Trop de requêtes, réessayez dans un moment.'},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        import logging
        logging.getLogger('api').error(f"generate_post error: {e}")
        return Response({'error': 'Erreur interne lors de la génération.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def generate_variants(request):
    """Génère plusieurs variantes d'un post LinkedIn"""

    # Vérifier la limite de générations
    can_generate, error_response = check_generation_limit(request.user)
    if not can_generate:
        return error_response

    summary = request.data.get('summary', '')
    tone = request.data.get('tone', 'professionnel')
    images = request.FILES.getlist('images')
    num_variants = min(int(request.data.get('num_variants', 3)), 5)

    if images:
        img_error = validate_uploaded_images(images)
        if img_error:
            return Response({'error': img_error}, status=status.HTTP_400_BAD_REQUEST)

    # Template support
    template_id = request.data.get('template_id')
    template = None
    if template_id:
        try:
            template = PromptTemplate.objects.get(pk=int(template_id))
            if template.default_tone:
                tone = template.default_tone
        except (PromptTemplate.DoesNotExist, ValueError):
            pass

    if tone not in VALID_TONES:
        tone = 'professionnel'

    if not summary.strip() and not images:
        return Response(
            {'error': 'Veuillez fournir un résumé ou des images à analyser'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Résoudre et valider le modèle IA
    requested_model = request.data.get('model')
    user_plan = get_user_plan(request.user)
    model_id = resolve_model(requested_model, user_plan)
    is_allowed, model_error = validate_model_access(model_id, user_plan)
    if not is_allowed:
        return Response({'error': model_error}, status=status.HTTP_403_FORBIDDEN)

    try:
        # Analyser les images si présentes (toujours via Claude)
        image_context = None
        if images:
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            image_context = analyze_images_with_vision(client, images)

        # Construire le contexte
        if image_context and summary.strip():
            full_context = f"Contexte extrait des images :\n{image_context}\n\nRésumé additionnel :\n{summary}"
        elif image_context:
            full_context = f"Contexte extrait des images :\n{image_context}"
        else:
            full_context = summary

        # Appliquer le template prefix/suffix
        if template:
            prefix = template.prompt_prefix.strip()
            suffix = template.prompt_suffix.strip()
            if prefix:
                full_context = f"{prefix}\n\n{full_context}"
            if suffix:
                full_context = f"{full_context}\n\n{suffix}"

        # Enrichir avec recherche web si nécessaire
        web_context = enrich_context(full_context)

        # Générer plusieurs variantes
        objective = get_objective(request)
        platform = get_platform(request)
        use_profile = str(request.data.get('use_profile', 'true')).lower() != 'false'
        user_context = get_user_context(request)
        system_prompt = build_variants_system_prompt(objective, tone, num_variants, platform=platform, profile=user_context, web_context=web_context, use_profile=use_profile)

        variants_user_message = f"Voici le contexte à transformer en posts LinkedIn :\n\n{full_context}"
        if web_context:
            variants_user_message += f"\n\n---\n{web_context}"

        raw_content = generate_text(
            model_id=model_id,
            system_prompt=system_prompt,
            user_message=variants_user_message,
            max_tokens=4096,
        )
        raw_variants = [v.strip() for v in raw_content.split("---VARIANTE---") if v.strip()]

        # Extraire les hashtags de chaque variante
        variants = []
        variants_hashtags = []
        for v in raw_variants:
            body, tags = extract_hashtags(v)
            variants.append(body)
            variants_hashtags.append(tags)

        # Sauvegarder la première variante comme post principal
        post = None
        if raw_variants:
            post = GeneratedPost.objects.create(
                user=request.user,
                summary=summary if summary.strip() else (image_context[:500] if image_context else ''),
                tone=tone,
                generated_content=raw_variants[0]
            )

        # AI engagement recommendation
        recommended_index = 0
        if len(variants) > 1:
            try:
                rec_text = generate_text(
                    model_id=model_id,
                    system_prompt="Tu es un expert LinkedIn. Analyse ces variantes de post et indique le NUMÉRO (1, 2, ou 3) de celle qui aura le meilleur engagement. Réponds UNIQUEMENT avec le numéro.",
                    user_message="\n\n---\n\n".join([f"Variante {i+1}:\n{v}" for i, v in enumerate(variants)]),
                    max_tokens=50,
                ).strip()
                for char in rec_text:
                    if char.isdigit():
                        idx = int(char) - 1
                        if 0 <= idx < len(variants):
                            recommended_index = idx
                        break
            except Exception:
                pass

        increment_usage(request.user)

        return Response({
            'variants': variants,
            'variants_hashtags': variants_hashtags,
            'id': post.id if post else None,
            'image_analysis': image_context,
            'recommended_index': recommended_index,
        })

    except Exception as e:
        error_msg = str(e)
        if 'rate' in error_msg.lower() or '429' in error_msg:
            return Response({'error': 'Trop de requêtes, réessayez dans un moment.'},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        import logging
        logging.getLogger('api').error(f"generate_variants error: {e}")
        return Response({'error': 'Erreur interne lors de la génération.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def regenerate_single_variant(request):
    """Régénère une seule variante d'un post LinkedIn"""
    summary = request.data.get('summary', '')
    tone = request.data.get('tone', 'professionnel')
    existing_variants = request.data.get('existing_variants', [])
    variant_index = request.data.get('variant_index', 0)

    if tone not in VALID_TONES:
        tone = 'professionnel'

    if not summary.strip():
        return Response(
            {'error': 'Le résumé est requis pour régénérer'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Résoudre et valider le modèle IA
    requested_model = request.data.get('model')
    user_plan = get_user_plan(request.user)
    model_id = resolve_model(requested_model, user_plan)
    is_allowed, model_error = validate_model_access(model_id, user_plan)
    if not is_allowed:
        return Response({'error': model_error}, status=status.HTTP_403_FORBIDDEN)

    try:
        other_variants = [v for i, v in enumerate(existing_variants) if i != variant_index]
        avoid_context = ""
        if other_variants:
            avoid_context = "\n\nVoici les autres variantes déjà générées (génère quelque chose de DIFFÉRENT) :\n"
            for i, v in enumerate(other_variants):
                avoid_context += f"\n--- Variante existante {i+1} ---\n{v[:200]}...\n"

        objective = get_objective(request)
        platform = get_platform(request)
        use_profile = str(request.data.get('use_profile', 'true')).lower() != 'false'
        user_context = get_user_context(request)
        system_prompt = build_single_variant_prompt(objective, tone, platform=platform, profile=user_context, use_profile=use_profile)

        raw_content = generate_text(
            model_id=model_id,
            system_prompt=system_prompt,
            user_message=f"Contexte :\n{summary}{avoid_context}",
            max_tokens=1024,
        )
        body, tags = extract_hashtags(raw_content)

        return Response({
            'variant': body,
            'hashtags': tags,
            'variant_index': variant_index,
        })

    except Exception as e:
        error_msg = str(e)
        if 'rate' in error_msg.lower() or '429' in error_msg:
            return Response({'error': 'Trop de requêtes'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        import logging
        logging.getLogger('api').error(f"regenerate_single_variant error: {e}")
        return Response({'error': 'Erreur interne lors de la génération.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def generate_first_comment(request):
    """Generate an AI-suggested first comment for a LinkedIn post."""
    content = request.data.get('content', '').strip()
    tone = request.data.get('tone', 'professionnel')

    if not content:
        return Response({'error': 'Le contenu du post est requis'}, status=status.HTTP_400_BAD_REQUEST)

    # Résoudre et valider le modèle IA
    requested_model = request.data.get('model')
    user_plan = get_user_plan(request.user)
    model_id = resolve_model(requested_model, user_plan)
    is_allowed, model_error = validate_model_access(model_id, user_plan)
    if not is_allowed:
        return Response({'error': model_error}, status=status.HTTP_403_FORBIDDEN)

    try:
        user_context = get_user_context(request)

        system_prompt = f"""Tu es un expert LinkedIn qui écrit des premiers commentaires stratégiques.

Le premier commentaire est crucial car :
- Les commentaires ont 15x plus de poids algorithmique que les likes
- Poster un commentaire dans les 60 premières minutes booste la visibilité de 90%
- Il lance la conversation et encourage d'autres à commenter

RÈGLES:
- Écris UN SEUL commentaire court (2-4 phrases max)
- Ajoute de la valeur : contexte supplémentaire, question ouverte, ou ressource complémentaire
- Sois authentique, pas promotionnel
- Ton: {tone}
- Pas de hashtags, pas d'emojis excessifs (1-2 max)
- Retourne UNIQUEMENT le commentaire

{user_context}"""

        comment = generate_text(
            model_id=model_id,
            system_prompt=system_prompt,
            user_message=f"Écris un premier commentaire stratégique pour ce post LinkedIn :\n\n{content}",
            max_tokens=300,
        ).strip()
        for char in ['"', '\u201c', '\u201d', '\u00ab', '\u00bb']:
            if comment.startswith(char) and comment.endswith(char):
                comment = comment[1:-1]

        return Response({'comment': comment})

    except Exception as e:
        error_msg = str(e)
        if 'rate' in error_msg.lower() or '429' in error_msg:
            return Response({'error': 'Trop de requêtes'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        import logging
        logging.getLogger('api').error(f"generate_first_comment error: {e}")
        return Response({'error': 'Erreur interne.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_posts(request):
    posts = GeneratedPost.objects.filter(user=request.user)

    # Filter by platform
    platform = request.query_params.get('platform')
    if platform and platform != 'all':
        posts = posts.filter(platform=platform)

    # Filter by tone
    tone = request.query_params.get('tone')
    if tone:
        posts = posts.filter(tone=tone)

    # Filter by date range
    date_range = request.query_params.get('date_range')
    if date_range == '7':
        posts = posts.filter(created_at__gte=timezone.now() - timedelta(days=7))
    elif date_range == '30':
        posts = posts.filter(created_at__gte=timezone.now() - timedelta(days=30))

    # Search by content
    search = request.query_params.get('search')
    if search:
        posts = posts.filter(generated_content__icontains=search)

    serializer = GeneratedPostSerializer(posts[:50], many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_published_posts(request):
    """Liste les posts publiés avec stats, avec filtres optionnels"""
    posts = PublishedPost.objects.filter(user=request.user)

    platform = request.query_params.get('platform')
    if platform and platform != 'all':
        posts = posts.filter(platform=platform)

    tone = request.query_params.get('tone')
    if tone:
        posts = posts.filter(tone=tone)

    date_range = request.query_params.get('date_range')
    if date_range == '7':
        posts = posts.filter(published_at__gte=timezone.now() - timedelta(days=7))
    elif date_range == '30':
        posts = posts.filter(published_at__gte=timezone.now() - timedelta(days=30))

    search = request.query_params.get('search')
    if search:
        posts = posts.filter(content__icontains=search)

    data = [{
        'id': p.id,
        'content': p.content,
        'tone': p.tone,
        'published_at': p.published_at.isoformat(),
        'views': p.views,
        'likes': p.likes,
        'comments': p.comments,
        'shares': p.shares,
        'engagement_rate': p.engagement_rate,
        'has_images': p.has_images,
        'linkedin_post_id': p.linkedin_post_id,
        'platform': p.platform,
        'stats_updated_at': p.stats_updated_at.isoformat() if p.stats_updated_at else None,
    } for p in posts[:50]]

    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_post(request, pk):
    try:
        post = GeneratedPost.objects.get(pk=pk, user=request.user)
        serializer = GeneratedPostSerializer(post)
        return Response(serializer.data)
    except GeneratedPost.DoesNotExist:
        return Response(
            {'error': 'Post non trouvé'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def suggest_hashtags(request):
    """Suggère des hashtags pertinents pour un post donné"""
    content = request.data.get('content', '')

    if not content.strip():
        return Response(
            {'error': 'Le contenu du post est requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Résoudre et valider le modèle IA
    requested_model = request.data.get('model')
    user_plan = get_user_plan(request.user)
    model_id = resolve_model(requested_model, user_plan)
    is_allowed, model_error = validate_model_access(model_id, user_plan)
    if not is_allowed:
        return Response({'error': model_error}, status=status.HTTP_403_FORBIDDEN)

    try:
        raw = generate_text(
            model_id=model_id,
            system_prompt="""Tu es un expert LinkedIn. Suggère 5-8 hashtags pertinents pour le post fourni.
Retourne UNIQUEMENT les hashtags, un par ligne, commençant par #.
Choisis des hashtags populaires sur LinkedIn, en français et en anglais.""",
            user_message=f"Suggère des hashtags pour ce post LinkedIn :\n\n{content}",
            max_tokens=256,
        )
        hashtags = [tag.strip() for tag in raw.split('\n') if tag.strip().startswith('#')]

        return Response({'hashtags': hashtags})

    except Exception as e:
        error_msg = str(e)
        if 'rate' in error_msg.lower() or '429' in error_msg:
            return Response({'error': 'Trop de requêtes, réessayez dans un moment.'},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        import logging
        logging.getLogger('api').error(f"suggest_hashtags error: {e}")
        return Response({'error': 'Erreur interne.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def regenerate_hook(request):
    """Régénère uniquement le hook (première ligne) d'un post LinkedIn"""
    content = request.data.get('content', '')
    tone = request.data.get('tone', 'professionnel')
    current_hook = request.data.get('current_hook', '')

    if not content.strip():
        return Response(
            {'error': 'Le contenu du post est requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    valid_tones = ['professionnel', 'inspirant', 'storytelling', 'educatif', 'humoristique']
    if tone not in valid_tones:
        tone = 'professionnel'

    # Résoudre et valider le modèle IA
    requested_model = request.data.get('model')
    user_plan = get_user_plan(request.user)
    model_id = resolve_model(requested_model, user_plan)
    is_allowed, model_error = validate_model_access(model_id, user_plan)
    if not is_allowed:
        return Response({'error': model_error}, status=status.HTTP_403_FORBIDDEN)

    try:
        system_prompt = f"""Tu es un ghostwriter LinkedIn d'élite, spécialiste des hooks (phrases d'accroche).

Tu dois générer UNE SEULE nouvelle phrase d'accroche pour un post LinkedIn existant.

Le hook doit :
- Stopper le scroll immédiatement
- Être UNE SEULE LIGNE (courte et percutante, max 15 mots)
- Créer de la curiosité ou de l'émotion
- Être DIFFÉRENT du hook actuel

Techniques à utiliser (varie à chaque fois) :
- Déclaration choc : "J'ai refusé une augmentation de 30%."
- Question provocante : "Et si tout ce qu'on vous a appris était faux ?"
- Chiffre frappant : "97% des startups échouent. La mienne aussi."
- Histoire personnelle : "Il y a 2 ans, j'ai été viré."
- Confession : "Je vais vous dire un truc que personne n'ose dire."
- Pattern interrupt : "Arrêtez de chercher votre passion."
- Exclusion : "Ce post n'est pas pour tout le monde."

NE COMMENCE JAMAIS par un emoji, "Ravi de...", "Je suis heureux de...", "Aujourd'hui je voudrais..."

Ton : {tone}

Retourne UNIQUEMENT la phrase d'accroche, rien d'autre. Pas de guillemets."""

        user_context = get_user_context(request)
        if user_context:
            system_prompt += f"\n\n{user_context}"

        avoid_text = ""
        if current_hook:
            avoid_text = f"\n\nHook actuel (génère quelque chose de DIFFÉRENT) : {current_hook}"

        hook = generate_text(
            model_id=model_id,
            system_prompt=system_prompt,
            user_message=f"Voici le post LinkedIn (sans le hook) :\n\n{content}{avoid_text}",
            max_tokens=100,
        ).strip()
        # Nettoyer : enlever les guillemets si l'IA en met
        for char in ['"', "'", '\u201c', '\u201d', '\u00ab', '\u00bb']:
            hook = hook.strip(char)

        return Response({'hook': hook})

    except Exception as e:
        error_msg = str(e)
        if 'rate' in error_msg.lower() or '429' in error_msg:
            return Response({'error': 'Trop de requêtes'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        import logging
        logging.getLogger('api').error(f"regenerate_hook error: {e}")
        return Response({'error': 'Erreur interne.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Saved Drafts ────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def save_drafts(request):
    """Sauvegarder un ou plusieurs brouillons."""
    drafts_data = request.data.get('drafts', [])
    if not drafts_data:
        return Response({'error': 'Aucun brouillon fourni'}, status=status.HTTP_400_BAD_REQUEST)

    created = []
    for d in drafts_data[:10]:  # max 10 at once
        content = d.get('content', '').strip()
        if not content:
            continue
        title = content[:80].split('\n')[0].strip() or 'Brouillon'
        draft = SavedDraft.objects.create(
            user=request.user,
            title=title,
            content=content,
            hashtags=d.get('hashtags', []),
            tone=d.get('tone', ''),
            source=d.get('source', 'variant'),
        )
        created.append({
            'id': draft.id,
            'title': draft.title,
            'content': draft.content,
            'hashtags': draft.hashtags,
            'tone': draft.tone,
            'source': draft.source,
            'created_at': draft.created_at.isoformat(),
        })

    return Response({'saved': len(created), 'drafts': created}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_drafts(request):
    """Lister les brouillons sauvegardés."""
    drafts = SavedDraft.objects.filter(user=request.user)[:50]
    data = [{
        'id': d.id,
        'title': d.title,
        'content': d.content,
        'hashtags': d.hashtags,
        'tone': d.tone,
        'source': d.source,
        'created_at': d.created_at.isoformat(),
    } for d in drafts]
    return Response(data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_draft(request, pk):
    """Supprimer un brouillon."""
    try:
        draft = SavedDraft.objects.get(pk=pk, user=request.user)
        draft.delete()
        return Response({'message': 'Brouillon supprimé'})
    except SavedDraft.DoesNotExist:
        return Response({'error': 'Brouillon introuvable'}, status=status.HTTP_404_NOT_FOUND)
