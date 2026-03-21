"""
Autopilot — Génération et publication automatique de posts LinkedIn.
"""
import random
import logging
from datetime import timedelta

import pytz
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    AutopilotConfig, ScheduledPost, GeneratedPost, UserProfile,
    LinkedInAccount, CONTENT_MODE_CHOICES,
)
from .billing import check_generation_limit, increment_usage
from .llm import get_user_plan, resolve_model, generate_text
from .websearch import enrich_context
from .views import extract_hashtags, POST_MODE_INSTRUCTIONS

logger = logging.getLogger(__name__)

ANGLE_VARIATIONS = [
    "Partage une leçon personnelle apprise sur ce sujet. Raconte une expérience concrète.",
    "Donne 5 conseils actionnables sur ce sujet. Format liste numérotée.",
    "Raconte une histoire (storytelling) liée à ce sujet. Début accrocheur, rebondissement, leçon.",
    "Présente un mythe vs réalité sur ce sujet. Déconstruis une croyance populaire.",
    "Partage une opinion forte (mais défendable) sur ce sujet. Prends position.",
    "Donne un framework ou une méthode en étapes sur ce sujet. Format pas-à-pas.",
    "Compare avant/après ou problème/solution sur ce sujet. Montre la transformation.",
    "Partage des statistiques ou tendances récentes sur ce sujet. Analyse les implications.",
]


# ---------------------------------------------------------------------------
# Core autopilot logic
# ---------------------------------------------------------------------------

def pick_topic_and_angle(config: AutopilotConfig):
    """Pick a topic (round-robin, avoiding recently used) and a random angle."""
    topics = config.topics or []
    if not topics:
        return None, None

    last_used = config.last_topics_used or []

    # Find topics not recently used
    available = [t for t in topics if t not in last_used]
    if not available:
        # All used — reset and pick first
        available = topics

    topic = available[0]
    angle = random.choice(ANGLE_VARIATIONS)
    return topic, angle


def build_autopilot_prompt(config: AutopilotConfig, topic: str, angle: str, web_context: str):
    """Build system prompt + user message for autopilot generation."""
    tone = config.tone or 'professionnel'

    system_prompt = f"""Tu es un ghostwriter LinkedIn d'élite. Tu crées des posts qui génèrent des milliers de vues et d'interactions.

RÈGLE N°1 — LE HOOK (première ligne) :
La première ligne est la PLUS IMPORTANTE. Elle doit stopper le scroll. Techniques à utiliser :
- Déclaration choc ou contre-intuitive
- Question provocante
- Chiffre frappant
- Histoire personnelle
- Pattern interrupt
- Confession
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

    # Content mode instructions
    mode = config.content_mode or 'audience_growth'
    if mode in POST_MODE_INSTRUCTIONS:
        system_prompt += f"\n{POST_MODE_INSTRUCTIONS[mode]}"

    # Web search context
    if web_context:
        system_prompt += f"\n\n{web_context}"

    # User profile context
    try:
        profile = UserProfile.objects.get(user=config.user)
        user_ctx = profile.build_prompt_context()
        if user_ctx:
            system_prompt += f"\n\n{user_ctx}"
    except UserProfile.DoesNotExist:
        pass

    # Recent posts for anti-repetition
    recent = GeneratedPost.objects.filter(user=config.user).order_by('-created_at')[:3]
    if recent:
        snippets = [p.generated_content[:100] for p in recent]
        system_prompt += "\n\nPOSTS RÉCEMMENT PUBLIÉS (ne pas répéter les mêmes idées) :\n" + "\n".join(
            f"- {s}..." for s in snippets
        )

    user_message = f"Écris un post LinkedIn sur le sujet suivant : {topic}\n\nAngle à adopter : {angle}"
    if web_context:
        user_message += f"\n\n---\n{web_context}"

    return system_prompt, user_message


def generate_autopilot_post(config: AutopilotConfig, scheduled_at=None):
    """Generate a single autopilot post for the given config."""
    topic, angle = pick_topic_and_angle(config)
    if not topic:
        logger.warning(f"Autopilot: no topics for user {config.user.username}")
        return None

    # Web search enrichment
    web_context = ""
    if config.use_web_search:
        try:
            web_context = enrich_context(topic) or ""
        except Exception as e:
            logger.warning(f"Autopilot web search failed: {e}")

    system_prompt, user_message = build_autopilot_prompt(config, topic, angle, web_context)

    # Resolve model based on user's plan
    plan = get_user_plan(config.user)
    model_id = resolve_model(None, plan)

    # Generate
    generated_content = generate_text(
        model_id=model_id,
        system_prompt=system_prompt,
        user_message=user_message,
        max_tokens=1024,
    )

    body, hashtags = extract_hashtags(generated_content)

    # Save GeneratedPost for history
    GeneratedPost.objects.create(
        user=config.user,
        summary=f"[Autopilot] {topic}",
        tone=config.tone,
        generated_content=generated_content,
    )

    # Increment usage
    increment_usage(config.user)

    # Determine scheduled time
    if not scheduled_at:
        scheduled_at = timezone.now() + timedelta(minutes=2)

    # Determine autopilot_status based on mode
    if config.mode == 'full_auto':
        autopilot_status = 'auto_queued'
    else:
        autopilot_status = 'draft'

    # Create ScheduledPost
    post = ScheduledPost.objects.create(
        user=config.user,
        content=generated_content,
        scheduled_at=scheduled_at,
        status='pending',
        is_autopilot=True,
        autopilot_status=autopilot_status,
        autopilot_topic=topic,
    )

    # Update last_topics_used
    last = config.last_topics_used or []
    last.append(topic)
    config.last_topics_used = last[-10:]  # Keep last 10
    config.save(update_fields=['last_topics_used'])

    # Send email notification for semi-auto
    if config.mode == 'semi_auto':
        _send_approval_email(config.user, post, topic)

    return post


def _send_approval_email(user, post, topic):
    """Send email notification for semi-auto approval."""
    try:
        if not user.email:
            return
        snippet = post.content[:200]
        send_mail(
            subject="PostFlow : Un nouveau post attend votre approbation",
            message=f"""Bonjour {user.first_name or user.username},

L'autopilot PostFlow a généré un nouveau post sur le sujet : "{topic}"

Aperçu :
{snippet}...

Connectez-vous pour l'approuver ou le modifier :
https://postflow.app/autopilot

— PostFlow""",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
    except Exception as e:
        logger.warning(f"Autopilot email failed: {e}")


# ---------------------------------------------------------------------------
# Scheduler job
# ---------------------------------------------------------------------------

def run_autopilot():
    """Scheduled job — runs every 5 minutes. Checks all enabled configs for due slots."""
    now = timezone.now()
    configs = AutopilotConfig.objects.filter(is_enabled=True).select_related('user')

    for config in configs:
        try:
            _process_config(config, now)
        except Exception as e:
            logger.error(f"Autopilot error for {config.user.username}: {e}", exc_info=True)


def _process_config(config: AutopilotConfig, now):
    """Process a single autopilot config — check if a slot is due and generate."""
    user = config.user

    # Check LinkedIn connection (required for publishing)
    try:
        li = LinkedInAccount.objects.get(user=user)
        if li.is_expired:
            return  # Skip — expired token
    except LinkedInAccount.DoesNotExist:
        return  # Skip — no LinkedIn

    # Check generation credits
    can_generate, _ = check_generation_limit(user)
    if not can_generate:
        return

    # Convert now to user's timezone
    try:
        user_tz = pytz.timezone(config.timezone)
    except pytz.UnknownTimeZoneError:
        user_tz = pytz.timezone('Europe/Paris')

    local_now = now.astimezone(user_tz)
    current_day = local_now.weekday()  # 0=Monday
    current_time_str = local_now.strftime('%H:%M')

    slots = config.schedule_slots or []
    for slot in slots:
        slot_day = slot.get('day')
        slot_time = slot.get('time', '')

        if slot_day != current_day:
            continue

        # Check if within 5-minute window
        try:
            slot_h, slot_m = map(int, slot_time.split(':'))
            now_h, now_m = local_now.hour, local_now.minute
            slot_total = slot_h * 60 + slot_m
            now_total = now_h * 60 + now_m
            if not (0 <= now_total - slot_total < 5):
                continue
        except (ValueError, AttributeError):
            continue

        # Check if already generated for this slot today
        today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        already_exists = ScheduledPost.objects.filter(
            user=user,
            is_autopilot=True,
            autopilot_topic__isnull=False,
            created_at__gte=today_start,
            created_at__lt=today_end,
            scheduled_at__hour=slot_h,
        ).exists()

        if already_exists:
            continue

        # Compute the exact scheduled_at in UTC
        scheduled_local = local_now.replace(hour=slot_h, minute=slot_m, second=0, microsecond=0)
        if scheduled_local < now:
            # Slot already passed, schedule for 2 min from now
            scheduled_at = now + timedelta(minutes=2)
        else:
            scheduled_at = scheduled_local.astimezone(pytz.utc)

        logger.info(f"Autopilot: generating for {user.username} — slot {slot_time}")
        generate_autopilot_post(config, scheduled_at=scheduled_at)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_autopilot_config(request):
    """Get the user's autopilot config (creates default if none)."""
    config, _ = AutopilotConfig.objects.get_or_create(user=request.user)
    return Response({
        'is_enabled': config.is_enabled,
        'mode': config.mode,
        'schedule_slots': config.schedule_slots,
        'timezone': config.timezone,
        'topics': config.topics,
        'tone': config.tone,
        'content_mode': config.content_mode,
        'use_web_search': config.use_web_search,
    })


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_autopilot_config(request):
    """Create or update the user's autopilot config."""
    config, _ = AutopilotConfig.objects.get_or_create(user=request.user)
    data = request.data

    # Validate schedule_slots
    slots = data.get('schedule_slots', config.schedule_slots)
    if isinstance(slots, list):
        validated = []
        for s in slots[:7]:
            day = s.get('day')
            time_str = s.get('time', '')
            if isinstance(day, int) and 0 <= day <= 6 and ':' in str(time_str):
                validated.append({'day': day, 'time': str(time_str)})
        config.schedule_slots = validated

    # Validate topics
    topics = data.get('topics', config.topics)
    if isinstance(topics, list):
        config.topics = [str(t).strip() for t in topics[:20] if str(t).strip()]

    # Validate mode
    mode = data.get('mode')
    if mode in ('full_auto', 'semi_auto'):
        config.mode = mode

    # Validate tone
    tone = data.get('tone')
    valid_tones = [c[0] for c in AutopilotConfig.TONE_CHOICES]
    if tone in valid_tones:
        config.tone = tone

    # Validate content_mode
    content_mode = data.get('content_mode')
    valid_modes = [c[0] for c in CONTENT_MODE_CHOICES]
    if content_mode in valid_modes:
        config.content_mode = content_mode

    # Booleans
    if 'use_web_search' in data:
        config.use_web_search = bool(data['use_web_search'])

    if 'timezone' in data and isinstance(data['timezone'], str):
        try:
            pytz.timezone(data['timezone'])
            config.timezone = data['timezone']
        except pytz.UnknownTimeZoneError:
            pass

    # Enable/disable — validate requirements when enabling
    if 'is_enabled' in data:
        enabling = bool(data['is_enabled'])
        if enabling:
            # Validate requirements
            errors = []
            if not config.topics:
                errors.append("Ajoutez au moins un sujet")
            if not config.schedule_slots:
                errors.append("Ajoutez au moins un créneau horaire")
            try:
                LinkedInAccount.objects.get(user=request.user)
            except LinkedInAccount.DoesNotExist:
                errors.append("Connectez votre compte LinkedIn")

            # Check plan
            plan = get_user_plan(request.user)
            plan_limits = settings.PLAN_LIMITS.get(plan, settings.PLAN_LIMITS['free'])
            if not plan_limits.get('autopilot_enabled', False):
                errors.append("L'autopilot nécessite un abonnement Pro ou Business")

            if errors:
                return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

        config.is_enabled = enabling

    config.save()

    return Response({
        'is_enabled': config.is_enabled,
        'mode': config.mode,
        'schedule_slots': config.schedule_slots,
        'timezone': config.timezone,
        'topics': config.topics,
        'tone': config.tone,
        'content_mode': config.content_mode,
        'use_web_search': config.use_web_search,
    })


def _serialize_autopilot_post(post):
    return {
        'id': post.id,
        'content': post.content,
        'scheduled_at': post.scheduled_at.isoformat(),
        'status': post.status,
        'autopilot_status': post.autopilot_status,
        'autopilot_topic': post.autopilot_topic,
        'created_at': post.created_at.isoformat(),
        'published_at': post.published_at.isoformat() if post.published_at else None,
        'error_message': post.error_message,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_autopilot_queue(request):
    """List autopilot posts awaiting approval (drafts)."""
    posts = ScheduledPost.objects.filter(
        user=request.user,
        is_autopilot=True,
        autopilot_status='draft',
        status='pending',
    ).order_by('-created_at')

    return Response([_serialize_autopilot_post(p) for p in posts])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_autopilot_post(request, pk):
    """Approve a draft autopilot post. Optionally update content."""
    try:
        post = ScheduledPost.objects.get(pk=pk, user=request.user, is_autopilot=True)
    except ScheduledPost.DoesNotExist:
        return Response({'error': 'Post introuvable'}, status=status.HTTP_404_NOT_FOUND)

    if post.autopilot_status != 'draft':
        return Response({'error': 'Ce post n\'est pas en attente d\'approbation'}, status=status.HTTP_400_BAD_REQUEST)

    # Allow content edit
    new_content = request.data.get('content')
    if new_content and isinstance(new_content, str) and new_content.strip():
        post.content = new_content.strip()

    post.autopilot_status = 'approved'

    # If scheduled_at is in the past, reschedule to 2 min from now
    if post.scheduled_at <= timezone.now():
        post.scheduled_at = timezone.now() + timedelta(minutes=2)

    post.save()
    return Response(_serialize_autopilot_post(post))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_autopilot_post(request, pk):
    """Reject a draft autopilot post."""
    try:
        post = ScheduledPost.objects.get(pk=pk, user=request.user, is_autopilot=True)
    except ScheduledPost.DoesNotExist:
        return Response({'error': 'Post introuvable'}, status=status.HTTP_404_NOT_FOUND)

    if post.autopilot_status != 'draft':
        return Response({'error': 'Ce post n\'est pas en attente d\'approbation'}, status=status.HTTP_400_BAD_REQUEST)

    post.autopilot_status = 'rejected'
    post.status = 'cancelled'
    post.save()
    return Response(_serialize_autopilot_post(post))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def trigger_generation(request):
    """Manually trigger one autopilot generation (for testing / on-demand)."""
    config, _ = AutopilotConfig.objects.get_or_create(user=request.user)

    if not config.topics:
        return Response({'error': 'Ajoutez au moins un sujet'}, status=status.HTTP_400_BAD_REQUEST)

    can_generate, error_response = check_generation_limit(request.user)
    if not can_generate:
        return error_response

    post = generate_autopilot_post(config)
    if not post:
        return Response({'error': 'Impossible de générer le post'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response(_serialize_autopilot_post(post), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_autopilot_history(request):
    """List past autopilot posts (published, rejected, etc.)."""
    posts = ScheduledPost.objects.filter(
        user=request.user,
        is_autopilot=True,
    ).exclude(
        autopilot_status='draft',
    ).order_by('-created_at')[:50]

    return Response([_serialize_autopilot_post(p) for p in posts])
