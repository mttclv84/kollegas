import json
import logging
import re

logger = logging.getLogger(__name__)

# Etichette leggibili per le risorse dell'API (prima parte del percorso dopo /api/).
TIPI = {
    'eventi': 'Formazione', 'iscrizioni': 'Iscrizione', 'attivita': 'Attività catalogo', 'host': 'Host',
    'eccezioni': 'Eccezione calendario', 'stores': 'Store', 'aree': 'Area', 'ruoli': 'Ruolo',
    'users': 'Utente', 'richieste-cancellazione': 'Richiesta cancellazione',
    'ehs/sessioni': 'Sessione EHS', 'ehs/corsi': 'Corso EHS', 'ehs/fornitori': 'Fornitore EHS',
    'ehs/formazioni': 'Formazione EHS svolta', 'ehs/registri': 'Registro EHS', 'ehs/mansioni': 'Mansione EHS',
    'ehs/configurazione': 'Configurazione EHS', 'ehs/matrice': 'Matrice EHS', 'ehs/persone': 'Persona EHS',
}
AZIONI = {'POST': 'crea', 'PUT': 'modifica', 'PATCH': 'modifica', 'DELETE': 'elimina'}
# Richieste che non sono azioni dell'utente (lettura notifiche, rinnovo del token).
ESCLUSI = re.compile(r'notifiche|/auth/|/avvisi?/')
CAMPI_NASCOSTI = re.compile(r'password|token', re.I)
NOMI = ('nome_completo', 'attivita_nome', 'corso_nome', 'fornitore_ragione_sociale', 'nome', 'descrizione')


class AuditMiddleware:
    """Registra nell'audit log ogni operazione andata a buon fine che modifica dati
    (POST/PUT/PATCH/DELETE su /api/), di qualunque profilo. Le viste che scrivono già
    una voce esplicita (gestione account) non vengono duplicate."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in AZIONI or not request.path.startswith('/api/') or ESCLUSI.search(request.path):
            return self.get_response(request)

        corpo = self._leggi_corpo(request)
        try:
            from .models import AuditLog
            ultimo_id = AuditLog.objects.order_by('-id').values_list('id', flat=True).first() or 0
        except Exception:
            return self.get_response(request)

        response = self.get_response(request)
        try:
            self._registra(request, response, corpo, ultimo_id)
        except Exception:
            # Il registro non deve mai bloccare l'operazione dell'utente.
            logger.exception('Audit automatico non riuscito per %s %s', request.method, request.path)
        return response

    @staticmethod
    def _leggi_corpo(request):
        if 'json' not in (request.content_type or '') or int(request.META.get('CONTENT_LENGTH') or 0) > 20000:
            return {}
        try:
            dati = json.loads(request.body or b'{}')
        except (ValueError, Exception):
            return {}
        return {k: v for k, v in dati.items() if not CAMPI_NASCOSTI.search(k)} if isinstance(dati, dict) else {}

    def _registra(self, request, response, corpo, ultimo_id):
        from .models import AuditLog

        utente = getattr(request, 'user', None)
        if response.status_code >= 400 or not utente or not utente.is_authenticated:
            return
        if AuditLog.objects.filter(id__gt=ultimo_id, actor=utente).exists():
            return  # la vista ha già scritto la sua voce

        parti = [p for p in request.path[len('/api/'):].strip('/').split('/') if p]
        ids = [int(p) for p in parti if p.isdigit()]
        risorsa = '/'.join(p for p in parti if not p.isdigit())
        chiave = next((k for k in sorted(TIPI, key=len, reverse=True) if risorsa.startswith(k)), parti[0] if parti else '')
        sotto_azione = risorsa[len(chiave):].strip('/')

        dati = getattr(response, 'data', None)
        dati = dati if isinstance(dati, dict) else {}
        target_id = ids[0] if ids else dati.get('id')
        nome = next((str(dati[k]) for k in NOMI if dati.get(k)), '')
        if dati.get('user_cognome'):
            nome = f"{dati['user_cognome']} {dati.get('user_nome', '')} — {dati.get('attivita_nome', '')}".strip(' —')

        dettaglio = []
        if sotto_azione:
            dettaglio.append(f'Azione: {sotto_azione.replace("-", " ").replace("/", " ")}')
        if corpo:
            dettaglio.append(', '.join(f'{k}: {v}' for k, v in list(corpo.items())[:8])[:500])

        AuditLog.objects.create(
            actor=utente,
            azione='modifica' if request.method == 'POST' and sotto_azione else AZIONI[request.method],
            target_tipo=TIPI.get(chiave, chiave or 'altro'),
            target_id=target_id if isinstance(target_id, int) else None,
            target_repr=(nome or (f'#{target_id}' if target_id else ''))[:300],
            dettaglio=' · '.join(dettaglio),
        )


class SolaLetturaMiddleware:
    """Profili in sola lettura (es. guest): rifiuta ogni richiesta che modifica dati
    e i download di export. Sono consentiti solo login/logout e la lettura delle notifiche."""

    CONSENTITI = re.compile(r'^/api/auth/|notifiche')
    EXPORT = re.compile(r'/report/excel/|/stats/export/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        scrittura = request.method not in ('GET', 'HEAD', 'OPTIONS')
        if (path.startswith('/api/') and not self.CONSENTITI.search(path)
                and (scrittura or self.EXPORT.search(path)) and self._sola_lettura(request)):
            from django.http import JsonResponse
            return JsonResponse({'detail': 'Profilo in sola lettura: operazione non consentita.'}, status=403)
        return self.get_response(request)

    @staticmethod
    def _sola_lettura(request):
        from rest_framework_simplejwt.authentication import JWTAuthentication
        try:
            esito = JWTAuthentication().authenticate(request)
        except Exception:
            return False
        return bool(esito and esito[0].sola_lettura)
