from django.db import models


class Iscrizione(models.Model):
    STATO_CHOICES = [
        ('iscritto', 'Iscritto'),
        ('partecipato', 'Partecipato'),
        ('assente', 'Assente'),
    ]

    evento = models.ForeignKey(
        'events.Evento', on_delete=models.CASCADE, related_name='iscrizioni'
    )
    user = models.ForeignKey(
        'users.User', on_delete=models.CASCADE, related_name='iscrizioni'
    )
    stato = models.CharField(max_length=15, choices=STATO_CHOICES, default='iscritto')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Iscrizione'
        verbose_name_plural = 'Iscrizioni'
        unique_together = ('evento', 'user')
        ordering = ['evento__data', 'user__cognome']

    def __str__(self):
        return f'{self.user} — {self.evento} ({self.stato})'


class RichiestaCancellazione(models.Model):
    STATO_CHOICES = [
        ('pending', 'In attesa'),
        ('approvata', 'Approvata'),
        ('rifiutata', 'Rifiutata'),
    ]

    iscrizione = models.ForeignKey(
        Iscrizione, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='richieste_cancellazione'
    )
    richiedente = models.ForeignKey(
        'users.User', on_delete=models.CASCADE, related_name='richieste_inviate'
    )
    motivazione = models.TextField()
    stato = models.CharField(max_length=15, choices=STATO_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='richieste_processate'
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    notifica_letta = models.BooleanField(default=False)
    # Snapshot: filled when iscrizione is deleted so popup still shows info
    snap_attivita_nome = models.CharField(max_length=200, blank=True)
    snap_evento_data = models.DateField(null=True, blank=True)
    snap_partecipante_nome = models.CharField(max_length=200, blank=True)
    snap_store_nome = models.CharField(max_length=200, blank=True)
    snap_tipologia = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = 'Richiesta Cancellazione'
        verbose_name_plural = 'Richieste Cancellazione'
        ordering = ['-created_at']

    def __str__(self):
        return f'Richiesta #{self.id} — {self.richiedente} ({self.stato})'
