from django.conf import settings
from django.db import models


class RichiestaAssistenza(models.Model):
    """Suggerimento, idea o richiesta di aiuto di un utente: la legge e la gestisce solo l'Admin."""
    TIPO_CHOICES = [('suggerimento', 'Suggerimento'), ('idea', 'Idea'), ('aiuto', 'Aiuto')]
    STATO_CHOICES = [('nuova', 'Nuova'), ('in_lavorazione', 'In lavorazione'), ('completata', 'Completata')]

    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='richieste_assistenza')
    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES)
    sezione = models.CharField(max_length=100, blank=True)  # solo per "aiuto": la parte di Kollegas coinvolta
    testo = models.TextField()
    stato = models.CharField(max_length=15, choices=STATO_CHOICES, default='nuova')
    risposta = models.TextField(blank=True)
    risposta_il = models.DateTimeField(null=True, blank=True)
    risposto_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='assistenza_risposte')
    # False quando l'Admin risponde: l'utente vede un pallino finché non apre l'Assistenza.
    risposta_letta = models.BooleanField(default=True)
    creata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creata_il']
        verbose_name = 'Richiesta di assistenza'
        verbose_name_plural = 'Richieste di assistenza'

    def __str__(self):
        return f'{self.get_tipo_display()} di {self.utente} ({self.get_stato_display()})'
