"""Riempie l'ultimo accesso dei profili con l'ultimo "Accesso" già presente nell'Audit Log."""
from django.db import migrations
from django.db.models import Max


def riempi(apps, schema_editor):
    AuditLog = apps.get_model('users', 'AuditLog')
    User = apps.get_model('users', 'User')
    ultimi = (AuditLog.objects.filter(azione='accesso', actor__isnull=False)
              .values('actor').annotate(ultimo=Max('created_at')))
    for riga in ultimi:
        User.objects.filter(pk=riga['actor'], last_login__isnull=True).update(last_login=riga['ultimo'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0020_alter_auditlog_azione'),
    ]

    operations = [
        migrations.RunPython(riempi, migrations.RunPython.noop),
    ]
