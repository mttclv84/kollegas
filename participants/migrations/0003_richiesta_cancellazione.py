import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('participants', '0002_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RichiestaCancellazione',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('motivazione', models.TextField()),
                ('stato', models.CharField(choices=[('pending', 'In attesa'), ('approvata', 'Approvata'), ('rifiutata', 'Rifiutata')], default='pending', max_length=15)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('notifica_letta', models.BooleanField(default=False)),
                ('snap_attivita_nome', models.CharField(blank=True, max_length=200)),
                ('snap_evento_data', models.DateField(blank=True, null=True)),
                ('snap_partecipante_nome', models.CharField(blank=True, max_length=200)),
                ('snap_store_nome', models.CharField(blank=True, max_length=200)),
                ('iscrizione', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='richieste_cancellazione', to='participants.iscrizione')),
                ('richiedente', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='richieste_inviate', to=settings.AUTH_USER_MODEL)),
                ('processed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='richieste_processate', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Richiesta Cancellazione',
                'verbose_name_plural': 'Richieste Cancellazione',
                'ordering': ['-created_at'],
            },
        ),
    ]
