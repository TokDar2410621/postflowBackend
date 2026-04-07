from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0021_facebook_instagram_accounts'),
    ]

    operations = [
        migrations.AddField(
            model_name='generatedpost',
            name='platform',
            field=models.CharField(choices=[('linkedin', 'LinkedIn'), ('facebook', 'Facebook'), ('x', 'X (Twitter)'), ('instagram', 'Instagram')], db_index=True, default='linkedin', max_length=20),
        ),
        migrations.AddField(
            model_name='scheduledpost',
            name='platform',
            field=models.CharField(choices=[('linkedin', 'LinkedIn'), ('facebook', 'Facebook'), ('x', 'X (Twitter)'), ('instagram', 'Instagram')], db_index=True, default='linkedin', max_length=20),
        ),
        migrations.AddField(
            model_name='publishedpost',
            name='platform',
            field=models.CharField(choices=[('linkedin', 'LinkedIn'), ('facebook', 'Facebook'), ('x', 'X (Twitter)'), ('instagram', 'Instagram')], db_index=True, default='linkedin', max_length=20),
        ),
        migrations.AddField(
            model_name='publishedpost',
            name='external_post_id',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='ID du post externe'),
        ),
        migrations.AddField(
            model_name='saveddraft',
            name='platform',
            field=models.CharField(choices=[('linkedin', 'LinkedIn'), ('facebook', 'Facebook'), ('x', 'X (Twitter)'), ('instagram', 'Instagram')], db_index=True, default='linkedin', max_length=20),
        ),
    ]
