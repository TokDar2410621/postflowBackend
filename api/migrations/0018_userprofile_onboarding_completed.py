from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0017_autopilot'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='onboarding_completed',
            field=models.BooleanField(default=False, verbose_name='Onboarding terminé'),
        ),
    ]
