from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0007_add_images_data_to_scheduledpost'),
    ]

    operations = [
        migrations.AddField(
            model_name='scheduledpost',
            name='first_comment',
            field=models.TextField(blank=True, default='', verbose_name='Premier commentaire auto'),
        ),
    ]
