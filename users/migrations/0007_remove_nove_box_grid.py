from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_user_document'),
    ]

    operations = [
        migrations.DeleteModel(name='RichiestaModifica9BG'),
        migrations.DeleteModel(name='NoveBoxGrid'),
    ]
