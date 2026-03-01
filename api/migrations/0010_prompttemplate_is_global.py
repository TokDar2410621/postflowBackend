from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0009_linkedinaccount_headline_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='prompttemplate',
            name='is_global',
            field=models.BooleanField(db_index=True, default=False, verbose_name='Template global'),
        ),
    ]
