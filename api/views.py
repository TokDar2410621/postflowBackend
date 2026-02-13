import re
import base64
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
import anthropic

from .models import GeneratedPost, PublishedPost, PromptTemplate
from .serializers import GeneratePostSerializer, GeneratedPostSerializer


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
@parser_classes([MultiPartParser, FormParser, JSONParser])
def generate_post(request):
    """Génère un post LinkedIn à partir d'un résumé et/ou d'images"""

    # Récupérer les données
    summary = request.data.get('summary', '')
    tone = request.data.get('tone', 'professionnel')
    images = request.FILES.getlist('images')

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
    valid_tones = ['professionnel', 'inspirant', 'storytelling', 'educatif', 'humoristique']
    if tone not in valid_tones:
        tone = 'professionnel'

    # Vérifier qu'on a au moins un résumé ou des images
    if not summary.strip() and not images:
        return Response(
            {'error': 'Veuillez fournir un résumé ou des images à analyser'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not settings.ANTHROPIC_API_KEY:
        return Response(
            {'error': 'ANTHROPIC_API_KEY is not configured'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        # Étape 1: Analyser les images si présentes
        image_context = None
        if images:
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

        # Étape 2: Générer le post LinkedIn
        system_prompt = f"""Tu es un expert en création de contenu LinkedIn. À partir du contexte fourni, génère un post LinkedIn professionnel et engageant.

Règles :
- Commence par un hook accrocheur (première ligne percutante)
- Utilise des sauts de ligne pour aérer le texte
- Ajoute des emojis pertinents mais pas trop
- Termine par un appel à l'action ou une question
- Adapte le ton : {tone}
- Le post doit faire entre 150 et 300 mots
- N'utilise PAS de hashtags dans le corps du texte, ajoute 3-5 hashtags à la fin
- Retourne UNIQUEMENT le post, sans commentaire ni explication"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user", "content": f"Voici le contexte à transformer en post LinkedIn :\n\n{full_context}"}
            ]
        )

        generated_content = message.content[0].text

        # Extraire les hashtags du post
        body, hashtags = extract_hashtags(generated_content)

        # Sauvegarder en base de données (contenu complet avec hashtags)
        post = GeneratedPost.objects.create(
            user=request.user if request.user.is_authenticated else None,
            summary=summary if summary.strip() else (image_context[:500] if image_context else ''),
            tone=tone,
            generated_content=generated_content
        )

        return Response({
            'post': body,
            'hashtags': hashtags,
            'id': post.id,
            'image_analysis': image_context
        })

    except anthropic.RateLimitError:
        return Response(
            {'error': 'Trop de requêtes, réessayez dans un moment.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    except anthropic.AuthenticationError:
        return Response(
            {'error': 'Clé API Anthropic invalide ou expirée.'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def generate_variants(request):
    """Génère plusieurs variantes d'un post LinkedIn"""

    summary = request.data.get('summary', '')
    tone = request.data.get('tone', 'professionnel')
    images = request.FILES.getlist('images')
    num_variants = min(int(request.data.get('num_variants', 3)), 5)

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

    valid_tones = ['professionnel', 'inspirant', 'storytelling', 'educatif', 'humoristique']
    if tone not in valid_tones:
        tone = 'professionnel'

    if not summary.strip() and not images:
        return Response(
            {'error': 'Veuillez fournir un résumé ou des images à analyser'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not settings.ANTHROPIC_API_KEY:
        return Response(
            {'error': 'ANTHROPIC_API_KEY is not configured'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        # Analyser les images si présentes
        image_context = None
        if images:
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

        # Générer plusieurs variantes
        system_prompt = f"""Tu es un expert en création de contenu LinkedIn. À partir du contexte fourni, génère {num_variants} variantes DIFFÉRENTES d'un post LinkedIn.

Chaque variante doit avoir :
- Un angle ou une approche différente
- Un hook accrocheur unique
- Le même ton général : {tone}
- Entre 150 et 300 mots
- Des emojis pertinents
- 3-5 hashtags à la fin

IMPORTANT : Retourne les variantes séparées par "---VARIANTE---" (exactement ce séparateur).
Ne numérote pas les variantes, commence directement par le contenu.
Retourne UNIQUEMENT les posts, sans introduction ni commentaire."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": f"Voici le contexte à transformer en posts LinkedIn :\n\n{full_context}"}
            ]
        )

        # Parser les variantes
        raw_content = message.content[0].text
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
                user=request.user if request.user.is_authenticated else None,
                summary=summary if summary.strip() else (image_context[:500] if image_context else ''),
                tone=tone,
                generated_content=raw_variants[0]
            )

        # AI engagement recommendation
        recommended_index = 0
        if len(variants) > 1:
            try:
                rec_message = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=50,
                    system="Tu es un expert LinkedIn. Analyse ces variantes de post et indique le NUMÉRO (1, 2, ou 3) de celle qui aura le meilleur engagement. Réponds UNIQUEMENT avec le numéro.",
                    messages=[
                        {"role": "user", "content": "\n\n---\n\n".join([f"Variante {i+1}:\n{v}" for i, v in enumerate(variants)])}
                    ]
                )
                rec_text = rec_message.content[0].text.strip()
                for char in rec_text:
                    if char.isdigit():
                        idx = int(char) - 1
                        if 0 <= idx < len(variants):
                            recommended_index = idx
                        break
            except Exception:
                pass

        return Response({
            'variants': variants,
            'variants_hashtags': variants_hashtags,
            'id': post.id if post else None,
            'image_analysis': image_context,
            'recommended_index': recommended_index,
        })

    except anthropic.RateLimitError:
        return Response(
            {'error': 'Trop de requêtes, réessayez dans un moment.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    except anthropic.AuthenticationError:
        return Response(
            {'error': 'Clé API Anthropic invalide ou expirée.'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@parser_classes([JSONParser])
def regenerate_single_variant(request):
    """Régénère une seule variante d'un post LinkedIn"""
    summary = request.data.get('summary', '')
    tone = request.data.get('tone', 'professionnel')
    existing_variants = request.data.get('existing_variants', [])
    variant_index = request.data.get('variant_index', 0)

    valid_tones = ['professionnel', 'inspirant', 'storytelling', 'educatif', 'humoristique']
    if tone not in valid_tones:
        tone = 'professionnel'

    if not summary.strip():
        return Response(
            {'error': 'Le résumé est requis pour régénérer'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not settings.ANTHROPIC_API_KEY:
        return Response(
            {'error': 'ANTHROPIC_API_KEY is not configured'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        other_variants = [v for i, v in enumerate(existing_variants) if i != variant_index]
        avoid_context = ""
        if other_variants:
            avoid_context = "\n\nVoici les autres variantes déjà générées (génère quelque chose de DIFFÉRENT) :\n"
            for i, v in enumerate(other_variants):
                avoid_context += f"\n--- Variante existante {i+1} ---\n{v[:200]}...\n"

        system_prompt = f"""Tu es un expert en création de contenu LinkedIn. Génère UNE SEULE variante d'un post LinkedIn.

Règles :
- Hook accrocheur unique
- Ton : {tone}
- Entre 150 et 300 mots
- Emojis pertinents
- 3-5 hashtags à la fin
- Retourne UNIQUEMENT le post, sans commentaire ni explication
- L'angle doit être DIFFÉRENT des variantes existantes"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user", "content": f"Contexte :\n{summary}{avoid_context}"}
            ]
        )

        raw_content = message.content[0].text
        body, tags = extract_hashtags(raw_content)

        return Response({
            'variant': body,
            'hashtags': tags,
            'variant_index': variant_index,
        })

    except anthropic.RateLimitError:
        return Response({'error': 'Trop de requêtes'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def list_posts(request):
    if request.user.is_authenticated:
        posts = GeneratedPost.objects.filter(user=request.user)
    else:
        posts = GeneratedPost.objects.filter(user__isnull=True)

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
def list_published_posts(request):
    """Liste les posts publiés avec stats, avec filtres optionnels"""
    if request.user.is_authenticated:
        posts = PublishedPost.objects.filter(user=request.user)
    else:
        posts = PublishedPost.objects.filter(user__isnull=True)

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
        'stats_updated_at': p.stats_updated_at.isoformat() if p.stats_updated_at else None,
    } for p in posts[:50]]

    return Response(data)


@api_view(['GET'])
def get_post(request, pk):
    try:
        post = GeneratedPost.objects.get(pk=pk)
        serializer = GeneratedPostSerializer(post)
        return Response(serializer.data)
    except GeneratedPost.DoesNotExist:
        return Response(
            {'error': 'Post non trouvé'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['POST'])
@parser_classes([JSONParser])
def suggest_hashtags(request):
    """Suggère des hashtags pertinents pour un post donné"""
    content = request.data.get('content', '')

    if not content.strip():
        return Response(
            {'error': 'Le contenu du post est requis'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not settings.ANTHROPIC_API_KEY:
        return Response(
            {'error': 'ANTHROPIC_API_KEY is not configured'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            system="""Tu es un expert LinkedIn. Suggère 5-8 hashtags pertinents pour le post fourni.
Retourne UNIQUEMENT les hashtags, un par ligne, commençant par #.
Choisis des hashtags populaires sur LinkedIn, en français et en anglais.""",
            messages=[
                {"role": "user", "content": f"Suggère des hashtags pour ce post LinkedIn :\n\n{content}"}
            ]
        )

        raw = message.content[0].text
        hashtags = [tag.strip() for tag in raw.split('\n') if tag.strip().startswith('#')]

        return Response({'hashtags': hashtags})

    except anthropic.RateLimitError:
        return Response(
            {'error': 'Trop de requêtes, réessayez dans un moment.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    except anthropic.AuthenticationError:
        return Response(
            {'error': 'Clé API Anthropic invalide ou expirée.'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
