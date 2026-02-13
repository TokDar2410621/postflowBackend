from django.db import models
from django.contrib.auth.models import User


class LinkedInAccount(models.Model):
    """Stocke les tokens OAuth LinkedIn"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='linkedin_account', null=True, blank=True)
    linkedin_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255, blank=True)
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
    error_message = models.TextField(blank=True, verbose_name="Message d'erreur")
    published_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de publication effective")
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', '-updated_at']
        verbose_name = "Template de prompt"
        verbose_name_plural = "Templates de prompts"

    def __str__(self):
        return f"{self.name} ({self.default_tone})"


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
