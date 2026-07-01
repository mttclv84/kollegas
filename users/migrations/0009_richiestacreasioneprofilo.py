from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_add_raw_password'),
        ('stores', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='RichiestaCreazioneProfilo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cognome', models.CharField(max_length=100)),
                ('nome', models.CharField(max_length=100)),
                ('email', models.EmailField(max_length=254)),
                ('sesso', models.CharField(default='NS', max_length=2)),
                ('livello_accesso', models.CharField(default='base', max_length=10)),
                ('codice_matricola', models.CharField(blank=True, max_length=50)),
                ('commento_mapping', models.TextField(blank=True)),
                ('stato', models.CharField(
                    choices=[('pending', 'In attesa'), ('approvata', 'Approvata'), ('rifiutata', 'Rifiutata')],
                    default='pending', max_length=20,
                )),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('richiedente', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='richieste_creazione',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('store', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='stores.store',
                )),
                ('ruolo', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='users.role',
                )),
                ('processed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='richieste_creazione_processate',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Richiesta Creazione Profilo',
                'ordering': ['-created_at'],
            },
        ),
    ]
