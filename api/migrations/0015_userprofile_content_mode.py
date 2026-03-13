from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0014_cartoonavatar_cartoonusagerecord'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='content_mode',
            field=models.CharField(
                choices=[('audience_growth', "Création d'audience"), ('job_search', 'Recherche emploi')],
                default='audience_growth',
                max_length=20,
                verbose_name='Mode de contenu',
            ),
        ),
    ]
