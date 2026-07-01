from django.db import models
from django.db.models import Q


class TipologiaAttivita(models.TextChoices):
    LD = 'ld', 'L&D'
    RECRUITING = 'recruiting', 'RECRUITING'
    EHS = 'ehs', 'EHS'
    PAYROLL = 'payroll', 'PAYROLL'
    ALTRO = 'altro', 'ALTRO'


class ModalitaPartecipazione(models.TextChoices):
    PRESENZA = 'presenza', 'In Presenza'
    ONLINE = 'online', 'Online'
    BLENDED = 'blended', 'Blended'


class Host(models.Model):
    POSIZIONE_CHOICES = [
        ('interno', 'Interno'),
        ('esterno', 'Esterno'),
        ('consulente', 'Consulente'),
    ]

    descrizione = models.CharField(max_length=200)
    posizione = models.CharField(max_length=20, choices=POSIZIONE_CHOICES)
    nota = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Host'
        verbose_name_plural = 'Host'
        ordering = ['descrizione']

    def __str__(self):
        return self.descrizione


class AttivitaCatalogo(models.Model):
    nome = models.CharField(max_length=200)
    tipologia = models.CharField(max_length=20, choices=TipologiaAttivita.choices)
    dettaglio = models.CharField(max_length=200, blank=True)
    ruoli_destinatari = models.ManyToManyField(
        'users.Role', blank=True, related_name='attivita_destinate'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Attività Catalogo'
        verbose_name_plural = 'Attività Catalogo'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Evento(models.Model):
    data = models.DateField()
    ora_inizio = models.TimeField()
    ora_fine = models.TimeField()
    ore_totali = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    attivita = models.ForeignKey(
        AttivitaCatalogo, on_delete=models.PROTECT, related_name='eventi'
    )
    host = models.ForeignKey(
        Host, on_delete=models.PROTECT, related_name='eventi'
    )
    location_store = models.ForeignKey(
        'stores.Store', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='eventi_hosted'
    )
    location_esterna = models.CharField(max_length=300, blank=True)
    max_partecipanti = models.PositiveSmallIntegerField(
        default=0,
        help_text='0 = nessun limite'
    )
    modalita_partecipazione = models.CharField(
        max_length=20,
        choices=ModalitaPartecipazione.choices,
        default=ModalitaPartecipazione.PRESENZA
    )
    nota = models.TextField(blank=True)
    created_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True,
        related_name='eventi_creati'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Evento'
        verbose_name_plural = 'Eventi'
        ordering = ['data', 'ora_inizio']

    def __str__(self):
        return f'{self.data} — {self.attivita.nome}'

    def save(self, *args, **kwargs):
        self._calcola_ore_totali()
        super().save(*args, **kwargs)

    def _calcola_ore_totali(self):
        from datetime import datetime, date
        inizio = datetime.combine(date.today(), self.ora_inizio)
        fine = datetime.combine(date.today(), self.ora_fine)
        delta = fine - inizio
        minuti_totali = delta.seconds // 60
        minuti_effettivi = minuti_totali - 60  # pausa pranzo
        self.ore_totali = round(max(0, minuti_effettivi) / 60, 2)

    @property
    def location_display(self):
        if self.location_store:
            return str(self.location_store)
        return self.location_esterna or '—'

    @property
    def posti_disponibili(self):
        if self.max_partecipanti == 0:
            return None
        iscritti = self.iscrizioni.count()
        return max(0, self.max_partecipanti - iscritti)


class NotificaEvento(models.Model):
    TIPO_CHOICES = [('nuova', 'Nuova'), ('annullata', 'Annullata')]
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='nuova')
    snap_attivita_nome = models.CharField(max_length=200)
    snap_data = models.DateField()
    snap_location = models.CharField(max_length=300, blank=True)
    snap_creato_da = models.CharField(max_length=200, blank=True)
    snap_motivazione = models.CharField(max_length=500, blank=True)
    letta_da = models.ManyToManyField(
        'users.User', blank=True, related_name='notifiche_eventi_lette'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class EccezioneCalendario(models.Model):
    data = models.DateField()
    nome_evento = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Eccezione Calendario'
        verbose_name_plural = 'Eccezioni Calendario'
        ordering = ['data']

    def __str__(self):
        return f'{self.data} — {self.nome_evento}'
