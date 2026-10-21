import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


class AutomatismiGiornalieriMiddleware:
    """Fa partire gli automatismi EHS giornalieri alla prima richiesta API del giorno,
    in assenza di uno schedulatore (cron) sul server. Il controllo in memoria evita
    di interrogare il database a ogni richiesta; quello sul database (in services)
    garantisce un'unica esecuzione anche con più processi."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.ultimo_giorno = None

    def __call__(self, request):
        oggi = timezone.now().date()
        if self.ultimo_giorno != oggi and request.path.startswith('/api/'):
            self.ultimo_giorno = oggi
            try:
                from .services import esegui_automatismi_giornalieri
                esegui_automatismi_giornalieri()
            except Exception:
                # Un errore negli automatismi non deve mai bloccare l'uso di Kollegas.
                logger.exception('Automatismi EHS giornalieri non riusciti')
                self.ultimo_giorno = None
        return self.get_response(request)
