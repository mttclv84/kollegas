from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stores', '0002_add_portale_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='store',
            name='codice_store',
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
