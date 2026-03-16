import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api', '0015_userprofile_content_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='SavedDraft',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('content', models.TextField()),
                ('hashtags', models.JSONField(blank=True, default=list)),
                ('tone', models.CharField(blank=True, max_length=20)),
                ('source', models.CharField(choices=[('variant', 'Variante'), ('generated', 'Post généré'), ('extracted', 'Idée extraite')], default='variant', max_length=30)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saved_drafts', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Brouillon sauvegardé',
                'verbose_name_plural': 'Brouillons sauvegardés',
                'ordering': ['-created_at'],
            },
        ),
    ]
