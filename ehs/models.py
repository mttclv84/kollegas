from django.db import models


class EHSCorso(models.Model):
    codice = models.CharField(max_length=30, unique=True)  # es. "SCALE"
    nome = models.CharField(max_length=200)
    durata_ore = models.DecimalField(max_digits=4, decimal_places=1)
    descrizione = models.TextField(blank=True)
    attivo = models.BooleanField(default=True)
    # Se valorizzato, alla chiusura aula si calcola la scadenza per ogni
    # partecipante presente. Se null, il corso non prevede scadenza.
    scadenza_giorni = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = 'Corso EHS'
        verbose_name_plural = 'Corsi EHS'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class EHSSessione(models.Model):
    STATO_CHOICES = [
        ('RICHIESTA_INVIATA', 'Richiesta inviata dallo store'),
        ('DATA_PROPOSTA', 'Data proposta dal fornitore'),
        ('DATA_CONTROPROPOSTA', 'Nuova data proposta dallo store'),
        ('CONFERMATA', 'Data confermata, docente assegnato'),
        ('REGISTRO_INVIATO', 'Registro inviato al negozio'),
        ('SVOLTA', 'Sessione svolta, registro compilato ricevuto'),
        ('COMPLETATA', 'Completata'),
        ('ANNULLATA', 'Annullata'),
    ]

    corso = models.ForeignKey(EHSCorso, on_delete=models.PROTECT, related_name='sessioni')
    negozio = models.ForeignKey('stores.Store', on_delete=models.PROTECT, related_name='ehs_sessioni')
    creata_da = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='ehs_sessioni_create'
    )
    fornitore = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ehs_sessioni_gestite',
        limit_choices_to={'livello_accesso': 'fornitore'},
    )

    stato = models.CharField(max_length=30, choices=STATO_CHOICES, default='RICHIESTA_INVIATA')

    data_proposta = models.DateTimeField(null=True, blank=True)
    data_confermata = models.DateTimeField(null=True, blank=True)
    durata_ore = models.DecimalField(max_digits=4, decimal_places=1)

    docente_nome = models.CharField(max_length=200, blank=True, null=True)
    docente_telefono = models.CharField(max_length=30, blank=True, null=True)

    contatto_negozio_nome = models.CharField(max_length=200)
    contatto_negozio_telefono = models.CharField(max_length=30)  # tipicamente cell. P&C

    registro_file = models.FileField(upload_to='ehs/registri/', null=True, blank=True)
    registro_compilato_file = models.FileField(upload_to='ehs/registri_compilati/', null=True, blank=True)

    calendario_evento = models.OneToOneField(
        'events.Evento', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ehs_sessione',
    )

    # Chiusura formale dell'aula (fatta dal fornitore a fine sessione)
    data_chiusura = models.DateTimeField(null=True, blank=True)
    chiusa_da = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ehs_sessioni_chiuse',
        limit_choices_to={'livello_accesso': 'fornitore'},
    )

    creata_il = models.DateTimeField(auto_now_add=True)
    aggiornata_il = models.DateTimeField(auto_now=True)
    note = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Sessione EHS'
        verbose_name_plural = 'Sessioni EHS'
        ordering = ['-creata_il']

    def __str__(self):
        return f'{self.corso.codice} — {self.negozio} ({self.stato})'


class EHSPartecipante(models.Model):
    sessione = models.ForeignKey(EHSSessione, on_delete=models.CASCADE, related_name='partecipanti')
    utente = models.ForeignKey('users.User', on_delete=models.PROTECT, related_name='ehs_partecipazioni')
    iscritto_il = models.DateTimeField(auto_now_add=True)

    # Confermato dal fornitore in fase di chiusura aula
    presente = models.BooleanField(default=False)
    assente_motivo = models.CharField(max_length=200, blank=True, null=True)

    attestato_file = models.FileField(upload_to='ehs/attestati/', null=True, blank=True)
    attestato_caricato_il = models.DateTimeField(null=True, blank=True)

    completato = models.BooleanField(default=False)
    completato_il = models.DateTimeField(null=True, blank=True)

    # Calcolato alla chiusura aula, solo se presente=True e corso.scadenza_giorni valorizzato
    scadenza_formazione = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = 'Partecipante EHS'
        verbose_name_plural = 'Partecipanti EHS'
        unique_together = ('sessione', 'utente')
        ordering = ['sessione', 'utente__cognome']

    def __str__(self):
        return f'{self.utente} — {self.sessione}'


class EHSSessioneLog(models.Model):
    sessione = models.ForeignKey(EHSSessione, on_delete=models.CASCADE, related_name='log')
    stato_precedente = models.CharField(max_length=30, blank=True)
    stato_nuovo = models.CharField(max_length=30)
    utente = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='ehs_log_azioni')
    timestamp = models.DateTimeField(auto_now_add=True)
    nota = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Log Sessione EHS'
        verbose_name_plural = 'Log Sessioni EHS'
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.sessione} — {self.stato_precedente}→{self.stato_nuovo}'


class EHSNotificaScadenza(models.Model):
    partecipante = models.OneToOneField(
        EHSPartecipante, on_delete=models.CASCADE, related_name='notifica_scadenza'
    )
    negozio_destinatario = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='ehs_notifiche_scadenza')
    creata_il = models.DateTimeField(auto_now_add=True)
    letta = models.BooleanField(default=False)
    letta_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Notifica Scadenza EHS'
        verbose_name_plural = 'Notifiche Scadenza EHS'
        ordering = ['-creata_il']

    def __str__(self):
        return f'Scadenza {self.partecipante} — {self.negozio_destinatario}'
