from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0018_userprofile_onboarding_completed'),
    ]

    operations = [
        migrations.AddField(
            model_name='autopilotconfig',
            name='content_instructions',
            field=models.TextField(
                blank=True, default='',
                help_text="Instructions personnalisées pour guider la génération",
            ),
        ),
        migrations.AddField(
            model_name='autopilotconfig',
            name='content_types',
            field=models.JSONField(
                blank=True, default=list,
                help_text='Types de contenu à générer: ["post", "carousel", "infographic"]',
            ),
        ),
    ]
