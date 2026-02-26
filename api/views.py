import re
import base64
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
import anthropic

from .models import GeneratedPost, PublishedPost, PromptTemplate, UserProfile
from .serializers import GeneratePostSerializer, GeneratedPostSerializer

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
MAX_IMAGES = 5


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
    """Récupère le contexte du profil utilisateur pour injection dans le prompt"""
    if not request.user.is_authenticated:
        return ""
    try:
        profile = UserProfile.objects.get(user=request.user)
        return profile.build_prompt_context()
    except UserProfile.DoesNotExist:
        return ""


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
@permission_classes([AllowAny])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def generate_post(request):
    """Génère un post LinkedIn à partir d'un résumé et/ou d'images"""

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
        system_prompt = f"""Tu es un ghostwriter LinkedIn d'élite. Tu crées des posts qui génèrent des milliers de vues et d'interactions.

RÈGLE N°1 — LE HOOK (première ligne) :
La première ligne est la PLUS IMPORTANTE. Elle doit stopper le scroll. Techniques à utiliser :
- Déclaration choc ou contre-intuitive : "J'ai refusé une augmentation de 30%. Voici pourquoi."
- Question provocante : "Et si tout ce qu'on vous a appris sur le management était faux ?"
- Chiffre frappant : "97% des startups échouent. La mienne aussi. 3 fois."
- Histoire personnelle : "Il y a 2 ans, j'ai été viré. Meilleure chose qui me soit arrivée."
- Pattern interrupt : "Arrêtez de chercher votre passion. Sérieusement."
- Confession : "Je vais vous dire un truc que personne n'ose dire dans notre industrie."
NE COMMENCE JAMAIS par : "🚀 Ravi de...", "Je suis heureux de...", "Aujourd'hui je voudrais...", "🎉 Excited to..."

STRUCTURE :
- Hook percutant (1 ligne seule)
- Ligne vide
- Développement avec des phrases courtes et percutantes
- 1 idée par ligne, aère le texte avec des sauts de ligne
- Utilise des emojis avec parcimonie (2-4 max, jamais en début de post)
- Termine par un appel à l'action engageant ou une question ouverte

CONTRAINTES :
- Ton : {tone}
- Entre 150 et 300 mots
- N'utilise PAS de hashtags dans le corps du texte, ajoute 3-5 hashtags à la fin
- Retourne UNIQUEMENT le post, sans commentaire ni explication
- Écris comme un humain, pas comme un robot corporate"""

        user_context = get_user_context(request)
        if user_context:
            system_prompt += f"\n\n{user_context}"

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
        session_key = request.data.get('session_key', '')
        post = GeneratedPost.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_key=session_key if not request.user.is_authenticated else '',
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
@permission_classes([AllowAny])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def generate_variants(request):
    """Génère plusieurs variantes d'un post LinkedIn"""

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
        system_prompt = f"""Tu es un ghostwriter LinkedIn d'élite. Génère {num_variants} variantes RADICALEMENT DIFFÉRENTES d'un post LinkedIn.

RÈGLE N°1 — LE HOOK (première ligne de chaque variante) :
La première ligne doit stopper le scroll. Chaque variante DOIT utiliser une technique de hook DIFFÉRENTE parmi :
- Déclaration choc : "J'ai refusé une augmentation de 30%. Voici pourquoi."
- Question provocante : "Et si tout ce qu'on vous a appris sur le management était faux ?"
- Chiffre frappant : "97% des startups échouent. La mienne aussi. 3 fois."
- Histoire personnelle : "Il y a 2 ans, j'ai été viré. Meilleure chose qui me soit arrivée."
- Confession : "Je vais vous dire un truc que personne n'ose dire dans notre industrie."
NE COMMENCE JAMAIS par : "🚀 Ravi de...", "Je suis heureux de...", "Aujourd'hui je voudrais..."

CHAQUE VARIANTE doit avoir :
- Un angle et une structure narrative différente
- Un hook utilisant une technique différente des autres variantes
- Ton : {tone}
- Entre 150 et 300 mots
- Emojis avec parcimonie (2-4 max, jamais en début de post)
- 3-5 hashtags à la fin
- Un style humain, pas corporate

IMPORTANT : Sépare les variantes par "---VARIANTE---" (exactement ce séparateur).
Ne numérote pas, commence directement par le contenu.
Retourne UNIQUEMENT les posts, sans introduction ni commentaire."""

        user_context = get_user_context(request)
        if user_context:
            system_prompt += f"\n\n{user_context}"

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
        session_key = request.data.get('session_key', '')
        post = None
        if raw_variants:
            post = GeneratedPost.objects.create(
                user=request.user if request.user.is_authenticated else None,
                session_key=session_key if not request.user.is_authenticated else '',
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
@permission_classes([AllowAny])
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

        system_prompt = f"""Tu es un ghostwriter LinkedIn d'élite. Génère UNE SEULE nouvelle variante d'un post LinkedIn.

RÈGLE N°1 — LE HOOK :
La première ligne doit stopper le scroll. Utilise une de ces techniques :
- Déclaration choc ou contre-intuitive
- Question provocante
- Chiffre frappant
- Histoire personnelle brute
- Confession audacieuse
NE COMMENCE JAMAIS par : "🚀 Ravi de...", "Je suis heureux de...", "Aujourd'hui je voudrais..."

CONTRAINTES :
- Ton : {tone}
- Entre 150 et 300 mots
- Emojis avec parcimonie (2-4 max, jamais en début de post)
- 3-5 hashtags à la fin
- Retourne UNIQUEMENT le post, sans commentaire ni explication
- L'angle et le hook doivent être DIFFÉRENTS des variantes existantes
- Écris comme un humain, pas comme un robot corporate"""

        user_context = get_user_context(request)
        if user_context:
            system_prompt += f"\n\n{user_context}"

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
@permission_classes([AllowAny])
def list_posts(request):
    if request.user.is_authenticated:
        posts = GeneratedPost.objects.filter(user=request.user)
    else:
        session_key = request.query_params.get('session_key', '')
        if not session_key:
            return Response([])
        posts = GeneratedPost.objects.filter(session_key=session_key, user__isnull=True)

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
@permission_classes([AllowAny])
def get_post(request, pk):
    try:
        if request.user.is_authenticated:
            post = GeneratedPost.objects.get(pk=pk, user=request.user)
        else:
            session_key = request.query_params.get('session_key', '')
            post = GeneratedPost.objects.get(pk=pk, session_key=session_key, user__isnull=True)
        serializer = GeneratedPostSerializer(post)
        return Response(serializer.data)
    except GeneratedPost.DoesNotExist:
        return Response(
            {'error': 'Post non trouvé'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['POST'])
@permission_classes([AllowAny])
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


@api_view(['POST'])
@permission_classes([AllowAny])
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

    if not settings.ANTHROPIC_API_KEY:
        return Response(
            {'error': 'ANTHROPIC_API_KEY is not configured'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

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

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            system=system_prompt,
            messages=[
                {"role": "user", "content": f"Voici le post LinkedIn (sans le hook) :\n\n{content}{avoid_text}"}
            ]
        )

        hook = message.content[0].text.strip()
        # Nettoyer : enlever les guillemets si l'IA en met
        for char in ['"', "'", '\u201c', '\u201d', '\u00ab', '\u00bb']:
            hook = hook.strip(char)

        return Response({'hook': hook})

    except anthropic.RateLimitError:
        return Response(
            {'error': 'Trop de requêtes'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
