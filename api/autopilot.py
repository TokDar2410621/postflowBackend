"""
Autopilot — Génération et publication automatique de posts LinkedIn.

Supports 3 content types: post (text), carousel, infographic.
Picks type randomly from user's enabled content_types.
"""
import json
import random
import logging
from datetime import timedelta

import pytz
import anthropic
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
from .carousel import validate_slides, CAROUSEL_MODE_INSTRUCTIONS, TEMPLATE_INSTRUCTIONS
from .infographic import validate_infographic
from .images import generate_image_for_post
from .pdf_export import render_to_images

logger = logging.getLogger(__name__)

VALID_CONTENT_TYPES = {'post', 'carousel', 'infographic'}

# Themes for carousel/infographic rendering (subset of frontend themes)
RENDER_THEMES = [
    {"name": "Navy Gold", "bgColor": "#0f1e35", "textColor": "#ffffff", "accentColor": "#eab308", "accentLight": "#fef08a", "mutedColor": "#94a3b8", "decorStyle": "geometric"},
    {"name": "Charcoal", "bgColor": "#1c1c1e", "textColor": "#ffffff", "accentColor": "#ff6b6b", "accentLight": "#fca5a5", "mutedColor": "#9ca3af", "decorStyle": "lines"},
    {"name": "Forest", "bgColor": "#0d2b1e", "textColor": "#ffffff", "accentColor": "#34d399", "accentLight": "#a7f3d0", "mutedColor": "#6ee7b7", "decorStyle": "dots"},
    {"name": "Blanc Pro", "bgColor": "#ffffff", "textColor": "#0f172a", "accentColor": "#1e3a5f", "accentLight": "#93c5fd", "mutedColor": "#64748b", "decorStyle": "minimal"},
    {"name": "Slate Blue", "bgColor": "#0f172a", "textColor": "#f1f5f9", "accentColor": "#3b82f6", "accentLight": "#93c5fd", "mutedColor": "#64748b", "decorStyle": "geometric"},
    {"name": "Purple", "bgColor": "#1a0a2e", "textColor": "#f5f3ff", "accentColor": "#a855f7", "accentLight": "#c084fc", "mutedColor": "#a78bfa", "decorStyle": "dots"},
]

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

# Carousel templates to pick randomly
CAROUSEL_TEMPLATES = list(TEMPLATE_INSTRUCTIONS.keys())


# ---------------------------------------------------------------------------
# Shared helpers
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
        available = topics

    topic = available[0]
    angle = random.choice(ANGLE_VARIATIONS)
    return topic, angle


def pick_content_type(config: AutopilotConfig):
    """Pick a random content type from user's enabled types."""
    types = config.content_types or []
    valid = [t for t in types if t in VALID_CONTENT_TYPES]
    if not valid:
        return 'post'  # default
    return random.choice(valid)


def _get_user_context(config: AutopilotConfig):
    """Build full user context string from profile + custom instructions."""
    parts = []

    # User profile context
    try:
        profile = UserProfile.objects.get(user=config.user)
        ctx = profile.build_prompt_context()
        if ctx:
            parts.append(ctx)
    except UserProfile.DoesNotExist:
        pass

    # Custom autopilot instructions
    if config.content_instructions and config.content_instructions.strip():
        parts.append(
            f"INSTRUCTIONS SPÉCIFIQUES DE L'AUTEUR POUR LE CONTENU :\n{config.content_instructions.strip()}"
        )

    # Recent posts for anti-repetition (last 5 posts, 200 chars each)
    recent = GeneratedPost.objects.filter(user=config.user).order_by('-created_at')[:5]
    if recent:
        snippets = [p.generated_content[:200] for p in recent]
        parts.append(
            "POSTS RÉCEMMENT PUBLIÉS (ne pas répéter les mêmes idées, angles ou structures) :\n"
            + "\n".join(f"- {s}..." for s in snippets)
        )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Post generation (text only)
# ---------------------------------------------------------------------------

def _generate_post_content(config, topic, angle, web_context, kb_context=""):
    """Generate a text post."""
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

    mode = config.content_mode or 'audience_growth'
    if mode in POST_MODE_INSTRUCTIONS:
        system_prompt += f"\n{POST_MODE_INSTRUCTIONS[mode]}"

    if kb_context:
        system_prompt += f"\n\n{kb_context}"

    if web_context:
        system_prompt += f"\n\n{web_context}"

    user_ctx = _get_user_context(config)
    if user_ctx:
        system_prompt += f"\n\n{user_ctx}"

    user_message = f"Écris un post LinkedIn sur le sujet suivant : {topic}\n\nAngle à adopter : {angle}"

    plan = get_user_plan(config.user)
    model_id = resolve_model(None, plan)

    content = generate_text(
        model_id=model_id,
        system_prompt=system_prompt,
        user_message=user_message,
        max_tokens=1024,
    )

    return {'type': 'post', 'content': content}


# ---------------------------------------------------------------------------
# Carousel generation
# ---------------------------------------------------------------------------

def _generate_carousel_content(config, topic, angle, web_context, kb_context=""):
    """Generate a carousel (slides JSON + caption text)."""
    tone = config.tone or 'professionnel'
    num_slides = random.randint(6, 8)
    template = random.choice(CAROUSEL_TEMPLATES)

    mode = config.content_mode or 'audience_growth'
    mode_block = CAROUSEL_MODE_INSTRUCTIONS.get(mode, CAROUSEL_MODE_INSTRUCTIONS["audience_growth"])
    template_block = TEMPLATE_INSTRUCTIONS.get(template, "")

    user_ctx = _get_user_context(config)

    system_prompt = f"""Tu es un expert en creation de carousels LinkedIn viraux.
Tu generes le contenu structure d'un carousel au format JSON strict.

REGLES DE DESIGN LINKEDIN (TRES IMPORTANT):
- Les carousels viraux ont 10-20 mots MAX par slide
- Les titres sont COURTS et PERCUTANTS (5-8 mots max)
- Les bullets sont ultra-concis (max 12 mots chacun)
- La slide 1 (titre) doit STOPPER LE SCROLL avec un hook puissant
- La derniere slide (CTA) doit donner une instruction CLAIRE et SPECIFIQUE

REGLES TECHNIQUES:
- Retourne UNIQUEMENT du JSON valide, sans markdown, sans backticks, sans commentaire
- La premiere slide est TOUJOURS de type "title" avec un hook percutant
- La derniere slide est TOUJOURS de type "cta" (call to action)
- Les slides intermediaires peuvent etre: "content", "quote", "dialogue", "stats", "comparison", "list", "image_text", "highlight"
- Chaque slide "content" a soit des "bullets" (2-4 points concis), soit un "body" (paragraphe court)
- Maximum 1 slide "quote" par carousel
- Le contenu doit etre en francais
- Cree un fil narratif logique entre les slides
- VARIE les types de slides pour un carousel visuellement dynamique (ne mets pas que des "content")
- Adapte le ton: {tone}

QUAND UTILISER CHAQUE TYPE DE SLIDE:
- "content" : point cle avec bullets ou paragraphe (polyvalent)
- "stats" : mettre en avant UN chiffre cle percutant (ex: "78%", "+200K", "3x")
- "comparison" : opposer 2 idees, avant/apres, mythe/realite en 2 colonnes
- "list" : liste d'elements avec emojis (conseils, outils, etapes)
- "highlight" : une phrase impact forte, isolee, qui marque les esprits
- "quote" : citation d'un auteur ou expert
- "dialogue" : echange Q&A en bulles de chat
- "image_text" : texte + espace image (utiliser pour slides visuelles)

{template_block}
{mode_block}

SCHEMA JSON A RESPECTER (exemples de chaque type):
{{
  "slides": [
    {{ "type": "title", "title": "Titre accrocheur", "subtitle": "Sous-titre explicatif" }},
    {{ "type": "content", "title": "Point cle", "bullets": ["Point 1", "Point 2", "Point 3"] }},
    {{ "type": "stats", "stat_number": "78%", "stat_label": "des managers", "stat_description": "ne savent pas deleguer" }},
    {{ "type": "comparison", "left_title": "Avant", "left_items": ["Pas de process"], "right_title": "Apres", "right_items": ["Process clairs"] }},
    {{ "type": "list", "title": "Les outils", "list_items": [{{ "emoji": "🎯", "text": "Notion pour organiser" }}] }},
    {{ "type": "highlight", "highlight_text": "Le succes n'est pas un accident." }},
    {{ "type": "quote", "quote": "Citation inspirante", "author": "Auteur" }},
    {{ "type": "cta", "title": "Titre final", "cta_text": "Action a faire", "cta_subtitle": "Suivez-moi" }}
  ]
}}

{user_ctx}"""

    if kb_context:
        system_prompt += f"\n\n{kb_context}"

    if web_context:
        system_prompt += f"\n\n{web_context}"

    user_message = f"Cree un carousel LinkedIn de {num_slides} slides sur : {topic}\nAngle : {angle}"

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()

        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
            if raw.endswith('```'):
                raw = raw[:-3].strip()

        data = json.loads(raw)
        slides = data.get('slides', data if isinstance(data, list) else [])

        if not validate_slides(slides):
            logger.warning("Autopilot carousel: invalid slides structure, falling back to post")
            return _generate_post_content(config, topic, angle, web_context)

        # Generate a caption to accompany the carousel
        caption = _generate_carousel_caption(config, topic, slides)

        # Render slides to images via Playwright
        theme = random.choice(RENDER_THEMES)
        rendered_images = _render_carousel_images(slides, theme, user=config.user)

        if not rendered_images:
            logger.warning("Autopilot carousel: rendering failed, falling back to post + AI image")
            return _generate_post_content(config, topic, angle, web_context)

        return {
            'type': 'carousel',
            'content': caption,
            'images': rendered_images,
        }

    except Exception as e:
        logger.error(f"Autopilot carousel generation failed: {e}", exc_info=True)
        return _generate_post_content(config, topic, angle, web_context)


def _render_carousel_images(slides, theme, user=None):
    """Render carousel slides to PNG images via Playwright + frontend /render page."""
    try:
        frontend_url = settings.FRONTEND_URL

        # Get LinkedIn profile info for slide watermark
        linkedin_profile = None
        if user:
            try:
                li = LinkedInAccount.objects.get(user=user)
                linkedin_profile = {'name': li.name or '', 'headline': li.headline or '', 'profile_picture_url': li.profile_picture_url or ''}
            except LinkedInAccount.DoesNotExist:
                pass

        slides_data = []
        for i, slide in enumerate(slides):
            slides_data.append({
                'format': 'carousel',
                'slide': slide,
                'theme': theme,
                'index': i,
                'total': len(slides),
                'linkedInProfile': linkedin_profile,
                'textScale': 1,
            })

        images = render_to_images(slides_data, frontend_url, viewport_height=1080)
        logger.info(f"Autopilot: rendered {len(images)} carousel slides")
        return images

    except Exception as e:
        logger.error(f"Autopilot carousel rendering failed: {e}", exc_info=True)
        return []


def _render_infographic_image(infographic, theme):
    """Render infographic to a single PNG image via Playwright + frontend /render page."""
    try:
        frontend_url = settings.FRONTEND_URL

        slides_data = [{
            'format': 'infographic',
            'infographic': infographic,
            'theme': theme,
            'textScale': 1,
        }]

        images = render_to_images(slides_data, frontend_url, viewport_height=1350)
        logger.info(f"Autopilot: rendered infographic image")
        return images

    except Exception as e:
        logger.error(f"Autopilot infographic rendering failed: {e}", exc_info=True)
        return []


def _generate_carousel_caption(config, topic, slides):
    """Generate a short LinkedIn caption to accompany the carousel PDF."""
    tone = config.tone or 'professionnel'
    titles = [s.get('title', s.get('highlight_text', '')) for s in slides[:3]]
    preview = " | ".join(t for t in titles if t)

    system_prompt = f"""Tu es un expert LinkedIn. Écris une légende courte et accrocheuse pour accompagner un carousel LinkedIn.

RÈGLES :
- Maximum 100 mots
- Hook en première ligne (stopper le scroll)
- Mentionne que c'est un carousel (ex: "Swipe →", "Slides à sauvegarder")
- Termine par un CTA (commentaire, partage, follow)
- Ajoute 3-5 hashtags à la fin
- Ton : {tone}
- Retourne UNIQUEMENT la légende, sans explication"""

    user_message = f"Sujet du carousel : {topic}\nAperçu des slides : {preview}"

    plan = get_user_plan(config.user)
    model_id = resolve_model(None, plan)

    return generate_text(
        model_id=model_id,
        system_prompt=system_prompt,
        user_message=user_message,
        max_tokens=512,
    )


# ---------------------------------------------------------------------------
# Infographic generation
# ---------------------------------------------------------------------------

def _generate_infographic_content(config, topic, angle, web_context, kb_context=""):
    """Generate an infographic (items JSON + caption text)."""
    tone = config.tone or 'professionnel'
    num_items = random.randint(6, 9)

    user_ctx = _get_user_context(config)

    system_prompt = f"""Tu es un expert en creation de contenu visuel LinkedIn.
Tu generes le contenu structure d'une infographie au format JSON strict.

REGLES DE CONTENU:
- Le titre principal doit etre ACCROCHEUR et court (8-12 mots max)
- Le sous-titre explique la valeur en 1 phrase courte
- Chaque item a un titre COURT (3-6 mots) et une description CONCISE (15-25 mots)
- Le contenu doit etre en francais
- Le footer_cta est une invitation a suivre/partager
- Adapte le ton: {tone}

REGLES TECHNIQUES:
- Retourne UNIQUEMENT du JSON valide, sans markdown, sans backticks, sans commentaire
- Genere exactement {num_items} items
- Chaque item a obligatoirement: number (int), title (str), description (str)
- Champs optionnels par item: emoji (str, 1 emoji), stat_value (str, chiffre cle), category (str, "left" ou "right")

SCHEMA JSON A RESPECTER:
{{
  "infographic": {{
    "title": "Titre accrocheur de l'infographie",
    "subtitle": "Sous-titre explicatif court",
    "template": "grid-numbered",
    "items": [
      {{ "number": 1, "title": "Concept cle", "description": "Description courte et actionnable.", "emoji": "🎯" }},
      {{ "number": 2, "title": "Autre concept", "description": "Explication concise.", "stat_value": "78%" }}
    ],
    "footer_cta": "Suivez-moi pour plus de conseils"
  }}
}}

{user_ctx}"""

    if kb_context:
        system_prompt += f"\n\n{kb_context}"

    if web_context:
        system_prompt += f"\n\n{web_context}"

    user_message = f"Cree une infographie LinkedIn de {num_items} elements sur : {topic}\nAngle : {angle}"

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()

        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
            if raw.endswith('```'):
                raw = raw[:-3].strip()

        data = json.loads(raw)
        infographic = data.get('infographic', data if isinstance(data, dict) and 'items' in data else {})

        if not validate_infographic(infographic):
            logger.warning("Autopilot infographic: invalid structure, falling back to post")
            return _generate_post_content(config, topic, angle, web_context)

        caption = _generate_infographic_caption(config, topic, infographic)

        # Render infographic to image via Playwright
        theme = random.choice(RENDER_THEMES)
        rendered_images = _render_infographic_image(infographic, theme)

        if not rendered_images:
            logger.warning("Autopilot infographic: rendering failed, falling back to post + AI image")
            return _generate_post_content(config, topic, angle, web_context)

        return {
            'type': 'infographic',
            'content': caption,
            'images': rendered_images,
        }

    except Exception as e:
        logger.error(f"Autopilot infographic generation failed: {e}", exc_info=True)
        return _generate_post_content(config, topic, angle, web_context)


def _generate_infographic_caption(config, topic, infographic):
    """Generate a short LinkedIn caption to accompany the infographic."""
    tone = config.tone or 'professionnel'
    title = infographic.get('title', topic)

    system_prompt = f"""Tu es un expert LinkedIn. Écris une légende courte et accrocheuse pour accompagner une infographie LinkedIn.

RÈGLES :
- Maximum 100 mots
- Hook en première ligne
- Mentionne que c'est une infographie (ex: "Infographie à sauvegarder 📌")
- Termine par un CTA
- Ajoute 3-5 hashtags à la fin
- Ton : {tone}
- Retourne UNIQUEMENT la légende"""

    user_message = f"Sujet : {topic}\nTitre de l'infographie : {title}"

    plan = get_user_plan(config.user)
    model_id = resolve_model(None, plan)

    return generate_text(
        model_id=model_id,
        system_prompt=system_prompt,
        user_message=user_message,
        max_tokens=512,
    )


# ---------------------------------------------------------------------------
# Main generation dispatcher
# ---------------------------------------------------------------------------

def generate_autopilot_post(config: AutopilotConfig, scheduled_at=None):
    """Generate a single autopilot post for the given config."""
    topic, angle = pick_topic_and_angle(config)
    if not topic:
        logger.warning(f"Autopilot: no topics for user {config.user.username}")
        return None

    # Pick content type
    content_type = pick_content_type(config)
    logger.info(f"Autopilot: generating {content_type} for {config.user.username} on '{topic}'")

    # Web search enrichment
    web_context = ""
    if config.use_web_search:
        try:
            web_context = enrich_context(topic) or ""
        except Exception as e:
            logger.warning(f"Autopilot web search failed: {e}")

    # Knowledge base retrieval
    kb_context = ""
    try:
        from .knowledge_base import retrieve_relevant_chunks
        kb_context = retrieve_relevant_chunks(config.user, topic)
        if kb_context:
            logger.info(f"Autopilot: KB context retrieved for {config.user.username}")
    except Exception as e:
        logger.warning(f"Autopilot KB retrieval failed: {e}")

    # Generate content based on type
    if content_type == 'carousel':
        result = _generate_carousel_content(config, topic, angle, web_context, kb_context)
    elif content_type == 'infographic':
        result = _generate_infographic_content(config, topic, angle, web_context, kb_context)
    else:
        result = _generate_post_content(config, topic, angle, web_context, kb_context)

    actual_type = result['type']
    content = result['content']

    # Save GeneratedPost for history
    type_label = {'post': 'Post', 'carousel': 'Carousel', 'infographic': 'Infographie'}.get(actual_type, 'Post')
    GeneratedPost.objects.create(
        user=config.user,
        summary=f"[Autopilot {type_label}] {topic}",
        tone=config.tone,
        generated_content=content,
    )

    # Increment usage
    increment_usage(config.user)

    # Images: use rendered images for carousel/infographic, generate AI image for text posts
    images_data = result.get('images', [])
    if actual_type == 'post':
        # Text posts always get an AI-generated illustration
        try:
            image_result = generate_image_for_post(content, topic)
            if image_result:
                images_data = [image_result]
                logger.info(f"Autopilot: AI image generated for {config.user.username}")
            else:
                logger.warning(f"Autopilot: no AI image generated for {config.user.username}")
        except Exception as e:
            logger.warning(f"Autopilot image generation failed: {e}")
    else:
        logger.info(f"Autopilot: using {len(images_data)} rendered images for {actual_type}")

    # Determine scheduled time
    if not scheduled_at:
        scheduled_at = timezone.now() + timedelta(minutes=2)

    # Determine autopilot_status based on mode
    autopilot_status = 'auto_queued' if config.mode == 'full_auto' else 'draft'

    # Create ScheduledPost
    post = ScheduledPost.objects.create(
        user=config.user,
        content=content,
        scheduled_at=scheduled_at,
        status='pending',
        is_autopilot=True,
        autopilot_status=autopilot_status,
        autopilot_topic=f"[{type_label}] {topic}",
        images_data=images_data,
    )

    # Update last_topics_used
    last = config.last_topics_used or []
    last.append(topic)
    config.last_topics_used = last[-10:]
    config.save(update_fields=['last_topics_used'])

    # Send email notification for semi-auto
    if config.mode == 'semi_auto':
        _send_approval_email(config.user, post, topic, actual_type)

    return post


def _send_approval_email(user, post, topic, content_type='post'):
    """Send email notification for semi-auto approval."""
    try:
        if not user.email:
            return
        type_label = {'carousel': 'carousel', 'infographic': 'infographie'}.get(content_type, 'post')
        snippet = post.content[:200]
        send_mail(
            subject=f"PostFlow : Un nouveau {type_label} attend votre approbation",
            message=f"""Bonjour {user.first_name or user.username},

L'autopilot PostFlow a généré un nouveau {type_label} sur le sujet : "{topic}"

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

    if not configs.exists():
        return

    logger.info(f"Autopilot job: checking {configs.count()} active config(s) at {now.isoformat()}")

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
            logger.info(f"Autopilot: skipping {user.username} — LinkedIn token expired")
            return
    except LinkedInAccount.DoesNotExist:
        logger.info(f"Autopilot: skipping {user.username} — no LinkedIn account")
        return

    # Check generation credits
    can_generate, _ = check_generation_limit(user)
    if not can_generate:
        logger.info(f"Autopilot: skipping {user.username} — no credits")
        return

    # Convert now to user's timezone
    try:
        user_tz = pytz.timezone(config.timezone)
    except pytz.UnknownTimeZoneError:
        user_tz = pytz.timezone('Europe/Paris')

    local_now = now.astimezone(user_tz)
    current_day = local_now.weekday()

    slots = config.schedule_slots or []
    today_slots = [s for s in slots if s.get('day') == current_day]

    if not today_slots:
        return

    logger.info(f"Autopilot: {user.username} — day {current_day}, local time {local_now.strftime('%H:%M')}, {len(today_slots)} slot(s) today")

    for slot in today_slots:
        slot_time = slot.get('time', '')

        # Check if within 10-minute window (more forgiving than strict 5min)
        try:
            slot_h, slot_m = map(int, slot_time.split(':'))
            now_h, now_m = local_now.hour, local_now.minute
            slot_total = slot_h * 60 + slot_m
            now_total = now_h * 60 + now_m
            diff = now_total - slot_total
            if not (0 <= diff <= 10):
                continue
        except (ValueError, AttributeError):
            continue

        logger.info(f"Autopilot: {user.username} — slot {slot_time} is due (diff={diff}min)")

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
            logger.info(f"Autopilot: {user.username} — slot {slot_time} already generated today, skipping")
            continue

        # Compute the exact scheduled_at in UTC
        scheduled_local = local_now.replace(hour=slot_h, minute=slot_m, second=0, microsecond=0)
        if scheduled_local < now:
            scheduled_at = now + timedelta(minutes=2)
        else:
            scheduled_at = scheduled_local.astimezone(pytz.utc)

        logger.info(f"Autopilot: generating for {user.username} — slot {slot_time}")
        generate_autopilot_post(config, scheduled_at=scheduled_at)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

def _serialize_config(config):
    """Serialize autopilot config to dict."""
    return {
        'is_enabled': config.is_enabled,
        'mode': config.mode,
        'schedule_slots': config.schedule_slots,
        'timezone': config.timezone,
        'topics': config.topics,
        'tone': config.tone,
        'content_mode': config.content_mode,
        'use_web_search': config.use_web_search,
        'content_instructions': config.content_instructions,
        'content_types': config.content_types,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_autopilot_config(request):
    """Get the user's autopilot config (creates default if none)."""
    config, _ = AutopilotConfig.objects.get_or_create(user=request.user)
    return Response(_serialize_config(config))


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
        for s in slots[:14]:  # up to 14 slots (2 per day)
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

    # Content instructions (free text)
    if 'content_instructions' in data:
        val = data['content_instructions']
        config.content_instructions = str(val)[:2000] if val else ''

    # Content types
    if 'content_types' in data:
        types = data['content_types']
        if isinstance(types, list):
            config.content_types = [t for t in types if t in VALID_CONTENT_TYPES]

    # Enable/disable — validate requirements when enabling
    if 'is_enabled' in data:
        enabling = bool(data['is_enabled'])
        if enabling:
            errors = []
            if not config.topics:
                errors.append("Ajoutez au moins un sujet")
            if not config.schedule_slots:
                errors.append("Ajoutez au moins un créneau horaire")
            try:
                LinkedInAccount.objects.get(user=request.user)
            except LinkedInAccount.DoesNotExist:
                errors.append("Connectez votre compte LinkedIn")

            plan = get_user_plan(request.user)
            plan_limits = settings.PLAN_LIMITS.get(plan, settings.PLAN_LIMITS['free'])
            if not plan_limits.get('autopilot_enabled', False):
                errors.append("L'autopilot nécessite un abonnement Pro ou Business")

            if errors:
                return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

        config.is_enabled = enabling

    config.save()
    return Response(_serialize_config(config))


def _serialize_autopilot_post(post):
    images = post.images_data if isinstance(post.images_data, list) else []
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
        'has_image': len(images) > 0,
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

    new_content = request.data.get('content')
    if new_content and isinstance(new_content, str) and new_content.strip():
        post.content = new_content.strip()

    post.autopilot_status = 'approved'

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
