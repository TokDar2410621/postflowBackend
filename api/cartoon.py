import base64
import logging

import anthropic
import requests
from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import CartoonAvatar, CartoonUsageRecord, Subscription

logger = logging.getLogger('api')

FLUX_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"

CARTOON_STYLE = (
    "cartoon character portrait, Pixar-inspired 3D style, upper body visible, "
    "friendly approachable expression, warm soft lighting, clean solid color background, "
    "professional LinkedIn style. "
    "IMPORTANT: no text, no letters, no words, no watermark, no typography."
)


# ========== Helpers ==========

def check_cartoon_limit(user):
    """Vérifie si l'utilisateur peut générer un cartoon. Returns (can_generate, error_response)"""
    if not user.is_authenticated:
        return False, Response({'error': 'Authentification requise'}, status=status.HTTP_401_UNAUTHORIZED)

    sub, _ = Subscription.objects.get_or_create(user=user)
    limits = settings.PLAN_LIMITS.get(sub.plan, settings.PLAN_LIMITS['free'])
    max_cartoons = limits.get('cartoon_per_month')

    if max_cartoons is None:
        return True, None

    now = timezone.now()
    usage, _ = CartoonUsageRecord.objects.get_or_create(
        user=user, year=now.year, month=now.month
    )

    if usage.cartoon_count >= max_cartoons:
        return False, Response({
            'error': f'Limite de {max_cartoons} cartoon(s)/mois atteinte. Passez au plan Pro.',
            'code': 'CARTOON_LIMIT_REACHED',
            'usage': {'current': usage.cartoon_count, 'limit': max_cartoons},
        }, status=status.HTTP_403_FORBIDDEN)

    return True, None


def increment_cartoon_usage(user):
    """Incrémente le compteur de cartoons du mois."""
    if not user.is_authenticated:
        return
    now = timezone.now()
    usage, _ = CartoonUsageRecord.objects.get_or_create(
        user=user, year=now.year, month=now.month
    )
    usage.cartoon_count += 1
    usage.save(update_fields=['cartoon_count', 'updated_at'])


def describe_photo_with_vision(photo_url):
    """Utilise Claude Vision pour décrire l'apparence physique d'une photo."""
    # Télécharger la photo
    resp = requests.get(photo_url, timeout=15)
    resp.raise_for_status()

    image_base64 = base64.b64encode(resp.content).decode('utf-8')
    content_type = resp.headers.get('content-type', 'image/jpeg')
    if content_type not in ('image/jpeg', 'image/png', 'image/gif', 'image/webp'):
        content_type = 'image/jpeg'

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": content_type,
                        "data": image_base64,
                    }
                },
                {
                    "type": "text",
                    "text": (
                        "Describe this person's physical appearance for a cartoon artist. Include: "
                        "apparent gender, approximate age, hair color and style, skin tone, "
                        "glasses (yes/no, style), facial hair (yes/no), visible clothing. "
                        "Respond in English, one concise descriptive sentence. "
                        "Do NOT include any name or identification."
                    )
                }
            ]
        }]
    )

    return message.content[0].text


def generate_cartoon_image(prompt_details, width=512, height=512):
    """Génère une image cartoon via Flux (HuggingFace)."""
    if not settings.HF_TOKEN:
        raise ValueError("HF_TOKEN non configuré")

    full_prompt = f"{CARTOON_STYLE} {prompt_details}"

    resp = requests.post(
        FLUX_URL,
        headers={"Authorization": f"Bearer {settings.HF_TOKEN}"},
        json={"inputs": full_prompt, "parameters": {"width": width, "height": height}},
        timeout=60,
    )

    if resp.status_code == 429:
        raise Exception("Limite de requêtes HuggingFace atteinte, réessayez plus tard")
    if resp.status_code == 503:
        raise Exception("Le modèle est en cours de chargement, réessayez dans quelques secondes")
    if resp.status_code != 200:
        raise Exception(f"Erreur HuggingFace: {resp.status_code}")

    image_base64 = base64.b64encode(resp.content).decode('utf-8')
    mime_type = resp.headers.get('content-type', 'image/jpeg')

    return image_base64, mime_type


def generate_dialogue_script(topic, tone, num_panels, main_name, other_name):
    """Génère le script de dialogue via Claude."""
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    system_prompt = (
        "Tu es un scénariste expert en dialogues éducatifs pour LinkedIn. "
        "Tu crées des dialogues naturels entre deux personnages pour expliquer un sujet. "
        "Le dialogue doit être engageant, pédagogique et adapté à LinkedIn."
    )

    user_message = f"""Génère un dialogue cartoon éducatif sur le sujet : "{topic}"

PERSONNAGES :
- {main_name} (personnage principal, expert)
- {other_name} (interlocuteur curieux)

RÈGLES :
- Exactement {num_panels} panneaux de dialogue
- Chaque panneau = 1 personnage parle (une bulle de texte)
- Alterne entre les personnages
- Panel 1 : {other_name} pose une question ou lance le sujet
- Panels 2 à {num_panels - 1} : échanges éducatifs, conseils, exemples concrets
- Panel {num_panels} : {main_name} conclut avec un conseil actionable ou CTA
- Chaque bulle : 15-30 mots maximum
- Ton : {tone}
- Langue : français

Réponds UNIQUEMENT avec du JSON valide, sans markdown :
{{"panels": [{{"speaker": "main", "text": "...", "speaker_name": "{main_name}"}}, {{"speaker": "other", "text": "...", "speaker_name": "{other_name}"}}]}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )

    import json
    raw = message.content[0].text.strip()
    # Nettoyer le markdown si présent
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
        if raw.endswith('```'):
            raw = raw[:-3]
        raw = raw.strip()

    return json.loads(raw)


# ========== Endpoints ==========

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_avatar(request):
    """Retourne l'avatar cartoon sauvegardé (s'il existe)."""
    try:
        cached = CartoonAvatar.objects.get(user=request.user)
        return Response({
            'avatar': cached.avatar_base64,
            'mime_type': cached.avatar_mime_type,
            'description': cached.appearance_description,
        })
    except CartoonAvatar.DoesNotExist:
        return Response({'avatar': None})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_avatar(request):
    """Étape 1 : Génère l'avatar cartoon à partir de la photo LinkedIn."""
    user = request.user

    # Vérifier si un avatar validé existe déjà
    try:
        linkedin = user.linkedin_account
        photo_url = linkedin.profile_picture_url
    except Exception:
        return Response(
            {'error': 'Connectez votre compte LinkedIn pour créer votre avatar cartoon.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not photo_url:
        return Response(
            {'error': 'Aucune photo de profil LinkedIn trouvée.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Vérifier le cache
    try:
        cached = CartoonAvatar.objects.get(user=user)
        if cached.source_photo_url == photo_url:
            return Response({
                'avatar': cached.avatar_base64,
                'mime_type': cached.avatar_mime_type,
                'description': cached.appearance_description,
                'is_cached': True,
            })
    except CartoonAvatar.DoesNotExist:
        pass

    try:
        # Claude Vision : décrire la photo
        description = describe_photo_with_vision(photo_url)

        # Flux : générer l'avatar cartoon
        avatar_base64, mime_type = generate_cartoon_image(
            f"Character based on this description: {description}"
        )

        return Response({
            'avatar': avatar_base64,
            'mime_type': mime_type,
            'description': description,
            'is_cached': False,
        })

    except Exception as e:
        logger.error(f"Erreur génération avatar cartoon: {e}")
        return Response(
            {'error': f'Erreur lors de la création de l\'avatar: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def validate_avatar(request):
    """Sauvegarde l'avatar validé par l'utilisateur."""
    user = request.user
    avatar_b64 = request.data.get('avatar', '')
    mime_type = request.data.get('mime_type', 'image/jpeg')
    description = request.data.get('description', '')

    if not avatar_b64:
        return Response({'error': 'Avatar manquant'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        photo_url = user.linkedin_account.profile_picture_url
    except Exception:
        photo_url = ''

    CartoonAvatar.objects.update_or_create(
        user=user,
        defaults={
            'avatar_base64': avatar_b64,
            'avatar_mime_type': mime_type,
            'appearance_description': description,
            'source_photo_url': photo_url,
        }
    )

    return Response({'status': 'ok', 'message': 'Avatar validé et sauvegardé.'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def regenerate_avatar(request):
    """Force la re-génération de l'avatar cartoon."""
    user = request.user

    try:
        linkedin = user.linkedin_account
        photo_url = linkedin.profile_picture_url
    except Exception:
        return Response(
            {'error': 'Connectez votre compte LinkedIn pour créer votre avatar cartoon.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not photo_url:
        return Response(
            {'error': 'Aucune photo de profil LinkedIn trouvée.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        description = describe_photo_with_vision(photo_url)
        avatar_base64, mime_type = generate_cartoon_image(
            f"Character based on this description: {description}"
        )

        return Response({
            'avatar': avatar_base64,
            'mime_type': mime_type,
            'description': description,
            'is_cached': False,
        })

    except Exception as e:
        logger.error(f"Erreur re-génération avatar cartoon: {e}")
        return Response(
            {'error': f'Erreur lors de la re-génération: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def generate_cartoon_dialogue(request):
    """Étape 2 : Génère le dialogue cartoon complet."""
    user = request.user

    topic = request.data.get('topic', '').strip()
    tone = request.data.get('tone', 'professionnel')
    num_panels = min(max(int(request.data.get('num_panels', 6)), 4), 8)
    main_name = request.data.get('main_character_name', user.first_name or 'Moi')
    other_name = request.data.get('other_character_name', 'Sophie')

    if not topic:
        return Response({'error': 'Le sujet est requis'}, status=status.HTTP_400_BAD_REQUEST)

    # Vérifier les limites
    can_generate, error_resp = check_cartoon_limit(user)
    if not can_generate:
        return error_resp

    # Récupérer l'avatar validé
    try:
        cached_avatar = CartoonAvatar.objects.get(user=user)
    except CartoonAvatar.DoesNotExist:
        return Response(
            {'error': 'Créez et validez votre avatar cartoon d\'abord.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Générer le second personnage
        other_avatar_b64, other_mime = generate_cartoon_image(
            f"A different cartoon character, professional look, relevant to the topic: {topic}. "
            f"Character named {other_name}."
        )

        # Générer le script de dialogue
        dialogue = generate_dialogue_script(topic, tone, num_panels, main_name, other_name)

        # Incrémenter l'usage
        increment_cartoon_usage(user)

        return Response({
            'panels': dialogue.get('panels', []),
            'characters': {
                'main': {
                    'name': main_name,
                    'avatar': cached_avatar.avatar_base64,
                    'mime_type': cached_avatar.avatar_mime_type,
                },
                'other': {
                    'name': other_name,
                    'avatar': other_avatar_b64,
                    'mime_type': other_mime,
                },
            },
            'metadata': {
                'topic': topic,
                'tone': tone,
                'generated_at': timezone.now().isoformat(),
            },
        })

    except Exception as e:
        logger.error(f"Erreur génération dialogue cartoon: {e}")
        return Response(
            {'error': f'Erreur lors de la génération du dialogue: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
