from django.db import migrations


def promuovi_admin_ehs(apps, schema_editor):
    User = apps.get_model('users', 'User')
    User.objects.filter(email__iexact='vspampinato@primark.it').update(livello_accesso='admin_ehs')


def rimuovi_promozione(apps, schema_editor):
    # Non riporta indietro il livello precedente: potrebbe essere stato cambiato
    # manualmente nel frattempo, meglio non sovrascriverlo alla cieca.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0015_alter_user_livello_accesso'),
    ]

    operations = [
        migrations.RunPython(promuovi_admin_ehs, rimuovi_promozione),
    ]
