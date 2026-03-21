from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api', '0016_saveddraft'),
    ]

    operations = [
        # Add autopilot fields to ScheduledPost
        migrations.AddField(
            model_name='scheduledpost',
            name='is_autopilot',
            field=models.BooleanField(default=False, verbose_name='Généré par autopilot'),
        ),
        migrations.AddField(
            model_name='scheduledpost',
            name='autopilot_status',
            field=models.CharField(
                blank=True,
                choices=[('', ''), ('draft', 'Brouillon autopilot'), ('approved', 'Approuvé'), ('rejected', 'Rejeté'), ('auto_queued', 'Auto programmé')],
                default='',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='scheduledpost',
            name='autopilot_topic',
            field=models.CharField(blank=True, max_length=200, verbose_name='Sujet autopilot'),
        ),
        # Create AutopilotConfig model
        migrations.CreateModel(
            name='AutopilotConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_enabled', models.BooleanField(default=False)),
                ('mode', models.CharField(choices=[('full_auto', 'Full Auto'), ('semi_auto', 'Semi Auto')], default='semi_auto', max_length=20)),
                ('schedule_slots', models.JSONField(blank=True, default=list)),
                ('timezone', models.CharField(default='Europe/Paris', max_length=50)),
                ('topics', models.JSONField(blank=True, default=list, help_text='Liste de sujets')),
                ('tone', models.CharField(choices=[('professionnel', 'Professionnel'), ('inspirant', 'Inspirant'), ('storytelling', 'Storytelling'), ('educatif', 'Éducatif'), ('humoristique', 'Humoristique')], default='professionnel', max_length=20)),
                ('content_mode', models.CharField(choices=[('audience_growth', "Création d'audience"), ('job_search', 'Recherche emploi'), ('lead_magnet', 'Lead magnet')], default='audience_growth', max_length=20)),
                ('use_web_search', models.BooleanField(default=True)),
                ('last_topics_used', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='autopilot_config', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Configuration Autopilot',
                'verbose_name_plural': 'Configurations Autopilot',
            },
        ),
    ]
