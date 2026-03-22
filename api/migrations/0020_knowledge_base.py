"""
Add Knowledge Base models with pgvector support.
KnowledgeBaseDocument stores uploaded documents (text extracted).
KnowledgeBaseChunk stores text chunks with vector embeddings for semantic search.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import pgvector.django


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api', '0019_autopilotconfig_content_instructions_and_types'),
    ]

    operations = [
        # Enable pgvector extension in PostgreSQL
        pgvector.django.VectorExtension(),

        # KnowledgeBaseDocument
        migrations.CreateModel(
            name='KnowledgeBaseDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=300)),
                ('source_type', models.CharField(choices=[('pdf', 'PDF'), ('txt', 'Text'), ('docx', 'DOCX'), ('url', 'URL'), ('paste', 'Pasted text')], max_length=10)),
                ('source_url', models.URLField(blank=True, default='', max_length=500)),
                ('raw_text', models.TextField(blank=True, default='')),
                ('chunk_count', models.IntegerField(default=0)),
                ('status', models.CharField(choices=[('processing', 'Processing'), ('ready', 'Ready'), ('error', 'Error')], default='processing', max_length=20)),
                ('error_message', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='kb_documents', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Document KB',
                'verbose_name_plural': 'Documents KB',
                'ordering': ['-created_at'],
            },
        ),

        # KnowledgeBaseChunk
        migrations.CreateModel(
            name='KnowledgeBaseChunk',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField()),
                ('chunk_index', models.IntegerField()),
                ('embedding', pgvector.django.VectorField(dimensions=1536)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('document', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chunks', to='api.knowledgebasedocument')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='kb_chunks', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Chunk KB',
                'verbose_name_plural': 'Chunks KB',
                'ordering': ['chunk_index'],
            },
        ),
    ]
