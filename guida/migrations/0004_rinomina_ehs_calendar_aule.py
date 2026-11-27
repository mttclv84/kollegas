"""La voce di menu "EHS Calendar & Richieste" diventa "EHS Calendar & Aule": aggiorna i testi della guida già salvati."""
from django.db import migrations


def rinomina(apps, schema_editor):
    Argomento = apps.get_model('guida', 'ArgomentoGuida')
    for a in Argomento.objects.filter(contenuto__contains='EHS Calendar & Richieste'):
        a.contenuto = a.contenuto.replace('EHS Calendar & Richieste', 'EHS Calendar & Aule')
        a.save(update_fields=['contenuto'])


class Migration(migrations.Migration):

    dependencies = [
        ('guida', '0003_guida_ho_iniziale'),
    ]

    operations = [
        migrations.RunPython(rinomina, migrations.RunPython.noop),
    ]
