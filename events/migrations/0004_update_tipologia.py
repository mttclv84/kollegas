from django.db import migrations, models


def migrate_tipologie(apps, schema_editor):
    AttivitaCatalogo = apps.get_model('events', 'AttivitaCatalogo')
    # Assessment → recruiting; tutto il resto → ld (tranne 'altro' che resta)
    for a in AttivitaCatalogo.objects.all():
        nome_lower = a.nome.lower()
        if 'assessment' in nome_lower:
            a.tipologia = 'recruiting'
        elif a.tipologia == 'altro':
            pass  # rimane 'altro'
        else:
            a.tipologia = 'ld'
        a.save(update_fields=['tipologia'])


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0003_add_eccezione_calendario'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attivitacatalogo',
            name='tipologia',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('ld', 'L&D'),
                    ('recruiting', 'RECRUITING'),
                    ('ehs', 'EHS'),
                    ('payroll', 'PAYROLL'),
                    ('altro', 'ALTRO'),
                ],
            ),
        ),
        migrations.RunPython(migrate_tipologie, migrations.RunPython.noop),
    ]
