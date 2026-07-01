from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='percorsocrescita',
            name='ruolo_nome',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='percorsocrescita',
            name='store_nome',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name='percorsocrescita',
            name='descrizione',
            field=models.TextField(blank=True),
        ),
        migrations.AlterModelOptions(
            name='percorsocrescita',
            options={'ordering': ['data'], 'verbose_name': 'Percorso Crescita', 'verbose_name_plural': 'Percorsi Crescita'},
        ),
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('azione', models.CharField(choices=[('crea', 'Creazione'), ('modifica', 'Modifica'), ('disattiva', 'Disattivazione'), ('riattiva', 'Riattivazione')], max_length=20)),
                ('target_tipo', models.CharField(max_length=50)),
                ('target_id', models.IntegerField(blank=True, null=True)),
                ('target_repr', models.CharField(max_length=300)),
                ('dettaglio', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='azioni_log', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Audit Log',
                'verbose_name_plural': 'Audit Log',
                'ordering': ['-created_at'],
            },
        ),
    ]
