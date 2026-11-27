"""Audit Log: download di dati personali e riepilogo dell'adozione di Kollegas (solo Admin)."""
from datetime import timedelta

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .accesso import LIVELLI_SENZA_ACCESSO
from .models import AuditLog, User
from .permissions import IsAdmin


def log_download(user, tipo, oggetto='', dettaglio='', target_id=None):
    """Registra un download o un export. Non deve mai bloccare lo scaricamento."""
    try:
        if user is not None and getattr(user, 'is_authenticated', False):
            AuditLog.objects.create(actor=user, azione='download', target_tipo=tipo, target_id=target_id,
                                    target_repr=(oggetto or '')[:300], dettaglio=(dettaglio or '')[:500])
    except Exception:
        pass


def filtri_leggibili(params, chiavi):
    """'data_da: 2026-01-01 · store: 3' a partire dai filtri usati nell'export."""
    return ' · '.join(f'{k}: {params[k]}' for k in chiavi if params.get(k))


# Download generati nel browser (es. il PDF degli iscritti), che il frontend comunica qui.
DOWNLOAD_DAL_BROWSER = {'pdf_iscritti': 'PDF iscritti'}


class RegistraDownloadView(APIView):
    """POST /users/audit/download/ {tipo, oggetto, oggetto_id?} — solo i tipi previsti."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tipo = DOWNLOAD_DAL_BROWSER.get(request.data.get('tipo'))
        if not tipo:
            return Response({'detail': 'Tipo di download non previsto.'}, status=400)
        oggetto_id = request.data.get('oggetto_id')
        log_download(request.user, tipo, str(request.data.get('oggetto') or ''),
                     target_id=oggetto_id if isinstance(oggetto_id, int) else None)
        return Response({'ok': True}, status=201)


class AdozioneView(APIView):
    """GET /users/audit/adozione/ — per livello: profili con accesso, chi è entrato, chi mai,
    chi ha ancora la password temporanea, chi ha usato Kollegas negli ultimi 7 e 30 giorni."""
    permission_classes = [IsAdmin]

    def get(self, request):
        adesso = timezone.now()
        da_7, da_30 = adesso - timedelta(days=7), adesso - timedelta(days=30)
        profili = (User.objects.filter(is_active=True, sola_lettura=False)
                   .exclude(livello_accesso__in=LIVELLI_SENZA_ACCESSO)
                   .select_related('store').order_by('cognome', 'nome'))
        etichette = dict(User.LIVELLO_CHOICES)
        livelli, mai, temporanee = {}, [], []
        for u in profili:
            riga = livelli.setdefault(u.livello_accesso, {
                'livello': u.livello_accesso, 'etichetta': etichette.get(u.livello_accesso, u.livello_accesso),
                'totale': 0, 'entrati': 0, 'mai_entrati': 0, 'attivi_7': 0, 'attivi_30': 0, 'password_temporanea': 0})
            riga['totale'] += 1
            persona = {'id': u.id, 'nome': u.nome_completo, 'livello': riga['etichetta'],
                       'negozio': u.store.nome if u.store else ''}
            if u.last_login:
                riga['entrati'] += 1
                riga['attivi_7'] += u.last_login >= da_7
                riga['attivi_30'] += u.last_login >= da_30
            else:
                riga['mai_entrati'] += 1
                mai.append(persona)
            if u.deve_cambiare_password:
                riga['password_temporanea'] += 1
                temporanee.append({**persona, 'scadenza': u.password_scadenza,
                                   'scaduta': bool(u.password_scadenza and u.password_scadenza <= adesso)})
        ordine = [c for c, _ in User.LIVELLO_CHOICES]
        righe = sorted(livelli.values(), key=lambda r: ordine.index(r['livello']) if r['livello'] in ordine else 99)
        totale = {k: sum(r[k] for r in righe) for k in ('totale', 'entrati', 'mai_entrati', 'attivi_7', 'attivi_30',
                                                         'password_temporanea')}
        return Response({'livelli': righe, 'totale': totale, 'mai_entrati': mai, 'password_temporanea': temporanee})
