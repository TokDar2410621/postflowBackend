from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0022_add_platform_to_content_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='is_demo',
            field=models.BooleanField(db_index=True, default=False, verbose_name='Compte de démonstration'),
        ),
    ]
