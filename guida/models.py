from django.conf import settings
from django.db import models

from users.models import User


class ArgomentoGuida(models.Model):
    """Un argomento della guida in app, per un profilo: titolo, testo e uno screenshot.
    Lo scrive e lo modifica solo l'Admin; ogni profilo vede solo i propri argomenti."""
    profilo = models.CharField(max_length=10, choices=User.LIVELLO_CHOICES)
    titolo = models.CharField(max_length=150)
    # Testo semplice: righe vuote tra i paragrafi, "- " elenco puntato, "1. " numerato, **grassetto**.
    contenuto = models.TextField(blank=True)
    immagine = models.ImageField(upload_to='guida/', null=True, blank=True)
    ordine = models.PositiveIntegerField(default=0)
    attivo = models.BooleanField(default=True)
    aggiornato_il = models.DateTimeField(auto_now=True)
    aggiornato_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name='argomenti_guida_modificati')

    class Meta:
        ordering = ['profilo', 'ordine', 'id']
        verbose_name = 'Argomento della guida'
        verbose_name_plural = 'Argomenti della guida'

    def __str__(self):
        return f'{self.get_profilo_display()} — {self.titolo}'
