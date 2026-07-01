from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_percorso_ruolo_store_auditlog'),
        ('stores', '0003_add_codice_store'),
    ]

    operations = [
        migrations.CreateModel(
            name='NoveBoxGrid',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('anno', models.PositiveSmallIntegerField()),
                ('performance', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('gestione_se', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('capacita_strategica', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('agilita_relazionale', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('aspirazione_professionale', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('potenziale_complessivo', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('motivazione', models.BooleanField(blank=True, null=True)),
                ('mobilita', models.CharField(blank=True, choices=[('nazionale', 'Nazionale (I)'), ('nord', 'Nord (N)'), ('centro_sud', 'Centro-Sud (CS)'), ('non_mobile', 'Non mobile')], default='', max_length=20)),
                ('nuovo_in_ruolo', models.BooleanField(default=False)),
                ('is_gwu', models.BooleanField(default=False)),
                ('is_visual_manager', models.BooleanField(default=False)),
                ('stato', models.CharField(choices=[('bozza', 'Bozza'), ('inviato', 'Inviato')], default='bozza', max_length=10)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='nove_box_created', to=settings.AUTH_USER_MODEL)),
                ('store', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='nove_box_grid', to='stores.store')),
                ('submitted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='nove_box_submitted', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='nove_box_grid', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-anno'], 'unique_together': {('user', 'anno')}},
        ),
    ]
