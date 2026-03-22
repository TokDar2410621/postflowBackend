from django.db import models
from django.contrib.auth.models import User


class LinkedInAccount(models.Model):
    """Stocke les tokens OAuth LinkedIn"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='linkedin_account', null=True, blank=True)
    linkedin_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255, blank=True)
    profile_picture_url = models.URLField(max_length=500, blank=True, verbose_name="Photo de profil")
    headline = models.CharField(max_length=500, blank=True, verbose_name="Titre/Headline LinkedIn")
    access_token = models.TextField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Compte LinkedIn"
        verbose_name_plural = "Comptes LinkedIn"

    def __str__(self):
        return f"{self.name} ({self.linkedin_id})"

    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() >= self.expires_at


class GeneratedPost(models.Model):
    TONE_CHOICES = [
        ('professionnel', 'Professionnel'),
        ('inspirant', 'Inspirant'),
        ('storytelling', 'Storytelling'),
        ('educatif', 'Éducatif'),
        ('humoristique', 'Humoristique'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='generated_posts', null=True, blank=True)
    session_key = models.CharField(max_length=64, blank=True, db_index=True, verbose_name="Clé de session anonyme")
    summary = models.TextField(verbose_name="Résumé original")
    tone = models.CharField(max_length=20, choices=TONE_CHOICES, default='professionnel')
    generated_content = models.TextField(verbose_name="Contenu généré")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Post généré"
        verbose_name_plural = "Posts générés"

    def __str__(self):
        return f"Post {self.id} - {self.tone} - {self.created_at.strftime('%d/%m/%Y %H:%M')}"


class ScheduledPost(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('published', 'Publié'),
        ('failed', 'Échec'),
        ('cancelled', 'Annulé'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='scheduled_posts', null=True, blank=True)
    content = models.TextField(verbose_name="Contenu du post")
    scheduled_at = models.DateTimeField(verbose_name="Date de publication prévue")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    first_comment = models.TextField(blank=True, default='', verbose_name="Premier commentaire auto")
    error_message = models.TextField(blank=True, verbose_name="Message d'erreur")
    images_data = models.JSONField(default=list, blank=True, verbose_name="Images en base64",
                                    help_text="Liste de {data: base64, mime_type: str}")
    published_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de publication effective")

    # Autopilot fields
    is_autopilot = models.BooleanField(default=False, verbose_name="Généré par autopilot")
    AUTOPILOT_STATUS_CHOICES = [
        ('', ''),
        ('draft', 'Brouillon autopilot'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
        ('auto_queued', 'Auto programmé'),
    ]
    autopilot_status = models.CharField(max_length=20, choices=AUTOPILOT_STATUS_CHOICES, blank=True, default='')
    autopilot_topic = models.CharField(max_length=200, blank=True, verbose_name="Sujet autopilot")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['scheduled_at']
        verbose_name = "Post programmé"
        verbose_name_plural = "Posts programmés"

    def __str__(self):
        return f"Post programmé {self.id} - {self.scheduled_at.strftime('%d/%m/%Y %H:%M')} - {self.status}"


class PromptTemplate(models.Model):
    """Templates de prompts personnalisés"""
    TONE_CHOICES = [
        ('professionnel', 'Professionnel'),
        ('inspirant', 'Inspirant'),
        ('storytelling', 'Storytelling'),
        ('educatif', 'Éducatif'),
        ('humoristique', 'Humoristique'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='templates', null=True, blank=True)
    name = models.CharField(max_length=100, verbose_name="Nom du template")
    description = models.TextField(blank=True, verbose_name="Description")
    default_tone = models.CharField(max_length=20, choices=TONE_CHOICES, default='professionnel')
    prompt_prefix = models.TextField(blank=True, verbose_name="Préfixe du prompt",
                                     help_text="Texte ajouté au début du résumé")
    prompt_suffix = models.TextField(blank=True, verbose_name="Suffixe du prompt",
                                     help_text="Texte ajouté à la fin du résumé")
    is_default = models.BooleanField(default=False, verbose_name="Template par défaut")
    is_global = models.BooleanField(default=False, verbose_name="Template global", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', '-updated_at']
        verbose_name = "Template de prompt"
        verbose_name_plural = "Templates de prompts"

    def __str__(self):
        return f"{self.name} ({self.default_tone})"


class TwitterAccount(models.Model):
    """Stocke les tokens OAuth Twitter/X"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='twitter_account')
    twitter_id = models.CharField(max_length=100, unique=True)
    username = models.CharField(max_length=100)
    name = models.CharField(max_length=255, blank=True)
    profile_picture_url = models.URLField(max_length=500, blank=True)
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Compte Twitter/X"
        verbose_name_plural = "Comptes Twitter/X"

    def __str__(self):
        return f"@{self.username} ({self.twitter_id})"


class PublishedPost(models.Model):
    """Posts publiés avec leurs statistiques LinkedIn"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='published_posts', null=True, blank=True)
    linkedin_post_id = models.CharField(max_length=100, blank=True, verbose_name="ID du post LinkedIn")
    content = models.TextField(verbose_name="Contenu du post")
    published_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de publication")

    # Statistiques
    views = models.IntegerField(default=0, verbose_name="Vues")
    likes = models.IntegerField(default=0, verbose_name="Likes")
    comments = models.IntegerField(default=0, verbose_name="Commentaires")
    shares = models.IntegerField(default=0, verbose_name="Partages")

    # Métadonnées
    has_images = models.BooleanField(default=False, verbose_name="Contient des images")
    tone = models.CharField(max_length=20, blank=True, verbose_name="Ton utilisé")
    stats_updated_at = models.DateTimeField(null=True, blank=True, verbose_name="Dernière MAJ des stats")

    class Meta:
        ordering = ['-published_at']
        verbose_name = "Post publié"
        verbose_name_plural = "Posts publiés"

    def __str__(self):
        return f"Post publié {self.id} - {self.published_at.strftime('%d/%m/%Y %H:%M')}"

    @property
    def engagement_rate(self):
        """Calcule le taux d'engagement"""
        if self.views == 0:
            return 0
        return round(((self.likes + self.comments + self.shares) / self.views) * 100, 2)


CONTENT_MODE_CHOICES = [
    ('audience_growth', "Création d'audience"),
    ('job_search', 'Recherche emploi'),
    ('lead_magnet', 'Lead magnet'),
]


class UserProfile(models.Model):
    """Profil utilisateur avec contexte pour la génération IA"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    content_mode = models.CharField(
        max_length=20,
        choices=CONTENT_MODE_CHOICES,
        default='audience_growth',
        verbose_name="Mode de contenu",
    )
    role = models.CharField(max_length=200, blank=True, verbose_name="Rôle / Poste")
    industry = models.CharField(max_length=200, blank=True, verbose_name="Secteur d'activité")
    expertise = models.TextField(blank=True, verbose_name="Domaines d'expertise")
    target_audience = models.TextField(blank=True, verbose_name="Audience cible")
    writing_style = models.TextField(blank=True, verbose_name="Style d'écriture")
    bio = models.TextField(blank=True, verbose_name="Bio / Description")
    example_posts = models.TextField(blank=True, verbose_name="Exemples de posts")
    additional_context = models.TextField(blank=True, verbose_name="Contexte additionnel")
    onboarding_completed = models.BooleanField(default=False, verbose_name="Onboarding terminé")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Profil utilisateur"
        verbose_name_plural = "Profils utilisateurs"

    def __str__(self):
        return f"Profil de {self.user.username}"

    @property
    def has_context(self):
        return any([self.role, self.industry, self.expertise,
                    self.target_audience, self.writing_style, self.bio])

    def build_prompt_context(self):
        if not self.has_context:
            return ""
        parts = ["CONTEXTE DE L'AUTEUR :"]
        if self.role:
            parts.append(f"- Rôle : {self.role}")
        if self.industry:
            parts.append(f"- Secteur : {self.industry}")
        if self.expertise:
            parts.append(f"- Expertise : {self.expertise}")
        if self.target_audience:
            parts.append(f"- Audience cible : {self.target_audience}")
        if self.writing_style:
            parts.append(f"- Style d'écriture : {self.writing_style}")
        if self.bio:
            parts.append(f"- Bio : {self.bio}")
        if self.example_posts:
            parts.append(f"\nEXEMPLES DE POSTS QUE L'AUTEUR APPRÉCIE :\n{self.example_posts}")
        if self.additional_context:
            parts.append(f"\nCONTEXTE ADDITIONNEL :\n{self.additional_context}")
        if self.content_mode == 'job_search':
            parts.append("\n🎯 Objectif LinkedIn : RECHERCHE D'EMPLOI — Le contenu doit positionner l'auteur comme expert, attirer les recruteurs et démontrer ses compétences.")
        elif self.content_mode == 'lead_magnet':
            parts.append("\n🧲 Objectif LinkedIn : LEAD MAGNET — Le contenu doit donner de la valeur, teaser une ressource, et pousser les gens à commenter pour la recevoir.")
        else:
            parts.append("\n🎯 Objectif LinkedIn : CRÉATION D'AUDIENCE — Le contenu doit maximiser le reach, l'engagement et les partages.")
        parts.append("\nAdapte le post à ce profil. Utilise un vocabulaire et des exemples cohérents avec son secteur et son audience.")
        return "\n".join(parts)


class Subscription(models.Model):
    """Abonnement Stripe de l'utilisateur"""
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('pro', 'Pro'),
        ('business', 'Business'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('past_due', 'Past Due'),
        ('canceled', 'Canceled'),
        ('incomplete', 'Incomplete'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='subscription')
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='free')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    stripe_customer_id = models.CharField(max_length=255, blank=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, db_index=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Abonnement"
        verbose_name_plural = "Abonnements"

    def __str__(self):
        return f"{self.user.username} - {self.plan} ({self.status})"

    @property
    def is_active(self):
        return self.status in ('active', 'past_due')

    @property
    def is_paid(self):
        return self.plan in ('pro', 'business') and self.is_active


class CartoonAvatar(models.Model):
    """Avatar cartoon généré à partir de la photo LinkedIn de l'utilisateur"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cartoon_avatar')
    appearance_description = models.TextField(verbose_name="Description de l'apparence")
    avatar_base64 = models.TextField(verbose_name="Avatar cartoon (base64)")
    avatar_mime_type = models.CharField(max_length=50, default='image/jpeg')
    source_photo_url = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Avatar cartoon"
        verbose_name_plural = "Avatars cartoon"

    def __str__(self):
        return f"Avatar de {self.user.username}"


class CartoonUsageRecord(models.Model):
    """Usage mensuel de dialogues cartoon par utilisateur"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cartoon_usage_records')
    year = models.IntegerField()
    month = models.IntegerField()
    cartoon_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'year', 'month')
        verbose_name = "Usage cartoon mensuel"
        verbose_name_plural = "Usages cartoon mensuels"

    def __str__(self):
        return f"{self.user.username} - {self.year}/{self.month}: {self.cartoon_count} cartoons"


class UsageRecord(models.Model):
    """Usage mensuel de générations par utilisateur"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='usage_records')
    year = models.IntegerField()
    month = models.IntegerField()
    generation_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'year', 'month')
        verbose_name = "Usage mensuel"
        verbose_name_plural = "Usages mensuels"

    def __str__(self):
        return f"{self.user.username} - {self.year}/{self.month}: {self.generation_count}"


class SavedDraft(models.Model):
    """Brouillon de post sauvegardé (variante, idée extraite, etc.)"""
    SOURCE_CHOICES = [
        ('variant', 'Variante'),
        ('generated', 'Post généré'),
        ('extracted', 'Idée extraite'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_drafts')
    title = models.CharField(max_length=200)
    content = models.TextField()
    hashtags = models.JSONField(default=list, blank=True)
    tone = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default='variant')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Brouillon sauvegardé"
        verbose_name_plural = "Brouillons sauvegardés"

    def __str__(self):
        return f"Draft {self.id} - {self.title[:50]}"


class AutopilotConfig(models.Model):
    """Configuration autopilot par utilisateur"""
    MODE_CHOICES = [
        ('full_auto', 'Full Auto'),
        ('semi_auto', 'Semi Auto'),
    ]
    TONE_CHOICES = [
        ('professionnel', 'Professionnel'),
        ('inspirant', 'Inspirant'),
        ('storytelling', 'Storytelling'),
        ('educatif', 'Éducatif'),
        ('humoristique', 'Humoristique'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='autopilot_config')
    is_enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='semi_auto')

    # Planning: [{"day": 0, "time": "09:00"}, ...] day: 0=Lundi
    schedule_slots = models.JSONField(default=list, blank=True)
    timezone = models.CharField(max_length=50, default='Europe/Paris')

    # Contenu
    topics = models.JSONField(default=list, blank=True, help_text="Liste de sujets")
    tone = models.CharField(max_length=20, choices=TONE_CHOICES, default='professionnel')
    content_mode = models.CharField(max_length=20, choices=CONTENT_MODE_CHOICES, default='audience_growth')
    use_web_search = models.BooleanField(default=True)
    content_instructions = models.TextField(
        blank=True, default='',
        help_text="Instructions personnalisées pour guider la génération (style, contexte, ton détaillé)"
    )
    content_types = models.JSONField(
        default=list, blank=True,
        help_text='Types de contenu à générer: ["post", "carousel", "infographic"]'
    )

    # Anti-répétition
    last_topics_used = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuration Autopilot"
        verbose_name_plural = "Configurations Autopilot"

    def __str__(self):
        status = "actif" if self.is_enabled else "inactif"
        return f"Autopilot {self.user.username} ({status})"


class KnowledgeBaseDocument(models.Model):
    """Document uploadé dans la base de connaissances."""
    SOURCE_CHOICES = [
        ('pdf', 'PDF'),
        ('txt', 'Text'),
        ('docx', 'DOCX'),
        ('url', 'URL'),
        ('paste', 'Pasted text'),
    ]
    STATUS_CHOICES = [
        ('processing', 'Processing'),
        ('ready', 'Ready'),
        ('error', 'Error'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='kb_documents')
    title = models.CharField(max_length=300)
    source_type = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    source_url = models.URLField(max_length=500, blank=True, default='')
    raw_text = models.TextField(blank=True, default='')
    chunk_count = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='processing')
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Document KB"
        verbose_name_plural = "Documents KB"

    def __str__(self):
        return f"[{self.source_type}] {self.title[:50]} ({self.status})"


class KnowledgeBaseChunk(models.Model):
    """Chunk de texte avec embedding vectoriel pour recherche sémantique."""
    from pgvector.django import VectorField

    document = models.ForeignKey(KnowledgeBaseDocument, on_delete=models.CASCADE, related_name='chunks')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='kb_chunks')
    content = models.TextField()
    chunk_index = models.IntegerField()
    embedding = VectorField(dimensions=1536)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['chunk_index']
        verbose_name = "Chunk KB"
        verbose_name_plural = "Chunks KB"

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.document.title[:30]}"
