from django.db import migrations


def crea_seed_data(apps, schema_editor):
    EHSCorso = apps.get_model('ehs', 'EHSCorso')
    Host = apps.get_model('events', 'Host')
    AttivitaCatalogo = apps.get_model('events', 'AttivitaCatalogo')

    EHSCorso.objects.get_or_create(
        codice='SCALE',
        defaults={'nome': 'SCALE', 'durata_ore': 3.0, 'scadenza_giorni': 365, 'attivo': True},
    )
    Host.objects.get_or_create(
        descrizione='Fornitore Esterno EHS',
        defaults={'posizione': 'esterno'},
    )
    AttivitaCatalogo.objects.get_or_create(
        nome='EHS',
        defaults={'tipologia': 'ehs'},
    )


def rimuovi_seed_data(apps, schema_editor):
    # Non rimuove i record: potrebbero già essere collegati a sessioni/eventi reali.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ehs', '0001_initial'),
        ('events', '0008_evento_ehs_luogo_evento_is_ehs'),
    ]

    operations = [
        migrations.RunPython(crea_seed_data, rimuovi_seed_data),
    ]
