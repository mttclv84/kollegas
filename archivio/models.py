from django.db import models


class FileArchiviato(models.Model):
    """Contenuto dei file caricati in app (registri, attestati, foto, documenti utente).
    Su Render il disco del server si azzera a ogni deploy: i file vivono quindi nel
    database PostgreSQL, che è persistente (vedi archivio.storage.DatabaseStorage)."""
    nome = models.CharField(max_length=500, unique=True)
    contenuto = models.BinaryField()
    dimensione = models.PositiveIntegerField(default=0)
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'File archiviato'
        verbose_name_plural = 'File archiviati'

    def __str__(self):
        return self.nome
