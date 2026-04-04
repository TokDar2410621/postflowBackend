from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api', '0020_knowledge_base'),
    ]

    operations = [
        migrations.CreateModel(
            name='FacebookAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('facebook_id', models.CharField(max_length=100, unique=True)),
                ('name', models.CharField(blank=True, max_length=255)),
                ('profile_picture_url', models.URLField(blank=True, max_length=500)),
                ('access_token', models.TextField()),
                ('page_id', models.CharField(blank=True, max_length=100)),
                ('page_access_token', models.TextField(blank=True)),
                ('token_expires_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='facebook_account', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Compte Facebook',
                'verbose_name_plural': 'Comptes Facebook',
            },
        ),
        migrations.CreateModel(
            name='InstagramAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('instagram_id', models.CharField(max_length=100, unique=True)),
                ('username', models.CharField(max_length=100)),
                ('name', models.CharField(blank=True, max_length=255)),
                ('profile_picture_url', models.URLField(blank=True, max_length=500)),
                ('access_token', models.TextField()),
                ('fb_page_id', models.CharField(blank=True, max_length=100)),
                ('token_expires_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='instagram_account', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Compte Instagram',
                'verbose_name_plural': 'Comptes Instagram',
            },
        ),
    ]
