from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from events.models import Evento
from stores.models import Store

from django.contrib.auth import get_user_model

from users.permissions import IsAdminOrHO

from . import services
from .models import (
    EHSCorso,
    EHSNotificaNuovaRichiesta,
    EHSNotificaScadenza,
    EHSNotificaSessioneConfermata,
    EHSSessione,
)
from .serializers import (
    EHSCalendarioEventoSerializer,
    EHSCorsoSerializer,
    EHSFornitoreSerializer,
    EHSSessioneDetailSerializer,
    EHSSessioneListSerializer,
)
from .services import TransizioneNonValida

User = get_user_model()

# Livelli con accesso alla sezione EHS (§4: la matrice permessi copre esplicitamente
# solo STORE/FORNITORE/ADMIN; HO è incluso per coerenza con il resto di Kollegas,
# dove è trattato quasi ovunque come equivalente ad ADMIN — vedi step 3).
RUOLI_EHS = ('store', 'fornitore', 'admin', 'ho')


def _parse_data(value):
    if not value:
        return None
    dt = parse_datetime(value)
    return dt


class EHSCorsoListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.livello_accesso not in RUOLI_EHS:
            return Response([])
        qs = EHSCorso.objects.filter(attivo=True)
        return Response(EHSCorsoSerializer(qs, many=True).data)


class EHSSessioneListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get_queryset_per_ruolo(self, user):
        qs = EHSSessione.objects.select_related('corso', 'negozio', 'fornitore', 'creata_da')
        if user.livello_accesso == 'store':
            qs = qs.filter(negozio=user.store)
        elif user.livello_accesso == 'fornitore':
            # Ogni fornitore vede ed agisce solo ed esclusivamente sulle proprie sessioni.
            qs = qs.filter(fornitore=user)
        return qs

    def get(self, request):
        user = request.user
        if user.livello_accesso not in RUOLI_EHS:
            return Response([])
        qs = self.get_queryset_per_ruolo(user)
        stato = request.query_params.get('stato')
        if stato:
            qs = qs.filter(stato=stato)
        return Response(EHSSessioneListSerializer(qs.order_by('-creata_il'), many=True).data)

    def post(self, request):
        user = request.user
        if user.livello_accesso not in ('store', 'admin', 'ho'):
            return Response({'detail': 'Non autorizzato.'}, status=403)

        corso_id = request.data.get('corso')
        contatto_nome = (request.data.get('contatto_negozio_nome') or '').strip()
        contatto_telefono = (request.data.get('contatto_negozio_telefono') or '').strip()
        note = request.data.get('note', '')
        partecipanti_previsti = request.data.get('partecipanti_previsti') or None
        data_suggerita_store = _parse_data(request.data.get('data_suggerita_store'))

        if not corso_id or not contatto_nome or not contatto_telefono:
            return Response({'detail': 'Corso, contatto negozio e telefono sono obbligatori.'}, status=400)

        try:
            corso = EHSCorso.objects.get(pk=corso_id, attivo=True)
        except EHSCorso.DoesNotExist:
            return Response({'detail': 'Corso non trovato.'}, status=404)

        if user.livello_accesso == 'store':
            negozio = user.store
            if not negozio:
                return Response({'detail': 'Utente senza negozio associato.'}, status=400)
        else:
            negozio_id = request.data.get('negozio')
            if not negozio_id:
                return Response({'detail': 'Negozio obbligatorio.'}, status=400)
            negozio = get_object_or_404(Store, pk=negozio_id)

        fornitore = None
        fornitore_id = request.data.get('fornitore')
        if fornitore_id:
            fornitore = get_object_or_404(User, pk=fornitore_id, livello_accesso='fornitore')

        try:
            sessione = services.crea_richiesta(
                user, corso, negozio, contatto_nome, contatto_telefono, note, fornitore=fornitore,
                partecipanti_previsti=partecipanti_previsti, data_suggerita_store=data_suggerita_store,
            )
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return Response(EHSSessioneDetailSerializer(sessione).data, status=201)


class BaseEHSSessioneActionView(APIView):
    """Base comune alle azioni sulla macchina a stati: recupera la sessione applicando
    la stessa visibilità per ruolo della lista (§4), senza duplicare la logica."""
    permission_classes = [IsAuthenticated]

    def get_sessione_visibile(self, request, pk):
        user = request.user
        qs = EHSSessioneListCreateView().get_queryset_per_ruolo(user)
        if user.livello_accesso in ('admin', 'ho'):
            qs = EHSSessione.objects.select_related('corso', 'negozio', 'fornitore', 'creata_da')
        return get_object_or_404(qs, pk=pk)


class EHSSessioneDetailView(BaseEHSSessioneActionView):
    def get(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        return Response(EHSSessioneDetailSerializer(sessione).data)


class EHSProponiDataView(BaseEHSSessioneActionView):
    def patch(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        data_proposta = _parse_data(request.data.get('data_proposta'))
        docente_nome = (request.data.get('docente_nome') or '').strip()
        docente_telefono = (request.data.get('docente_telefono') or '').strip()
        if not data_proposta:
            return Response({'detail': 'data_proposta obbligatoria (ISO datetime).'}, status=400)
        if not docente_nome or not docente_telefono:
            return Response({'detail': 'Nome e telefono del docente sono obbligatori.'}, status=400)
        try:
            sessione = services.proponi_data(sessione, request.user, data_proposta, docente_nome, docente_telefono)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return Response(EHSSessioneDetailSerializer(sessione).data)


class EHSRispondiDataView(BaseEHSSessioneActionView):
    def patch(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        accetta = bool(request.data.get('accetta'))
        nuova_data = _parse_data(request.data.get('nuova_data'))
        try:
            sessione = services.rispondi_data(sessione, request.user, accetta, nuova_data)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return Response(EHSSessioneDetailSerializer(sessione).data)


class EHSAccettaContropropostaView(BaseEHSSessioneActionView):
    """Il fornitore accetta così com'è la data contro-proposta dallo store."""
    def patch(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        try:
            sessione = services.accetta_controproposta(sessione, request.user)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return Response(EHSSessioneDetailSerializer(sessione).data)


class EHSChiudiAulaView(BaseEHSSessioneActionView):
    """Ultimo passaggio del wizard 'Aula completata': un solo submit multipart con
    le presenze per partecipante ('presente_<id>' bool, 'motivo_<id>' opzionale per
    gli assenti) e il registro compilato ('file', un solo documento per la sessione)."""
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        file = request.FILES.get('file')
        presenze, assenze_motivo = {}, {}
        for p in sessione.partecipanti.all():
            presenze[p.id] = str(request.data.get(f'presente_{p.id}', '')).lower() in ('true', '1', 'on')
            motivo = request.data.get(f'motivo_{p.id}')
            if motivo:
                assenze_motivo[p.id] = motivo
        try:
            sessione = services.chiudi_aula(sessione, presenze, file, request.user, assenze_motivo)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return Response(EHSSessioneDetailSerializer(sessione).data)


class EHSAssegnaFornitoreView(BaseEHSSessioneActionView):
    """Assegna un fornitore a una richiesta ancora senza fornitore (store o Admin/HO) —
    necessario perché un fornitore vede solo le proprie sessioni: senza assegnazione
    nessuno riceverebbe mai la richiesta."""
    def patch(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        fornitore_id = request.data.get('fornitore')
        if not fornitore_id:
            return Response({'detail': 'fornitore obbligatorio.'}, status=400)
        fornitore = get_object_or_404(User, pk=fornitore_id, livello_accesso='fornitore')
        try:
            sessione = services.assegna_fornitore(sessione, request.user, fornitore)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return Response(EHSSessioneDetailSerializer(sessione).data)


class EHSAnnullaView(BaseEHSSessioneActionView):
    def patch(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        try:
            sessione = services.annulla_sessione(sessione, request.user)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=400)
        return Response(EHSSessioneDetailSerializer(sessione).data)


class EHSCalendarioView(APIView):
    """GET /api/ehs/calendario/ — eventi del calendario principale (EHS e non, §5.6:
    'restano visibili in sola lettura tutti gli altri eventi'), nessun filtro per
    negozio: stessa visibilità del calendario Kollegas esistente (che oggi non
    restringe per store neanche per il ruolo store — vedi EventoListCreateView)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.livello_accesso not in RUOLI_EHS:
            return Response([])
        qs = Evento.objects.select_related(
            'attivita', 'location_store', 'ehs_sessione__corso', 'ehs_sessione__negozio',
        ).prefetch_related('iscrizioni')
        params = request.query_params
        if params.get('anno') and params.get('mese'):
            qs = qs.filter(data__year=params['anno'], data__month=params['mese'])
        return Response(EHSCalendarioEventoSerializer(qs.order_by('data', 'ora_inizio'), many=True).data)


DEFAULT_FORNITORE_PASSWORD = 'Primark01!'


class EHSFornitoreListCreateView(APIView):
    """Anagrafica fornitori EHS: gestita solo da Admin/HO, ma leggibile anche da
    Store/Fornitore (serve per il menù a tendina nella nuova richiesta)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.livello_accesso not in RUOLI_EHS:
            return Response([])
        qs = User.objects.filter(livello_accesso='fornitore')
        if request.user.livello_accesso not in ('admin', 'ho'):
            qs = qs.filter(is_active=True)
        return Response(EHSFornitoreSerializer(qs.order_by('fornitore_ragione_sociale'), many=True).data)

    def post(self, request):
        if request.user.livello_accesso not in ('admin', 'ho'):
            return Response({'detail': 'Solo Admin/HO possono creare fornitori EHS.'}, status=403)

        email = (request.data.get('email') or '').strip().lower()
        ragione_sociale = (request.data.get('fornitore_ragione_sociale') or '').strip()
        nome = (request.data.get('nome') or '').strip()
        telefono = (request.data.get('telefono') or '').strip()
        indirizzo = (request.data.get('indirizzo') or '').strip()
        if not email or not ragione_sociale or not nome or not telefono or not indirizzo:
            return Response(
                {'detail': 'Email, nome azienda, nome di riferimento, indirizzo e telefono sono obbligatori.'},
                status=400,
            )

        if User.objects.filter(email=email).exists():
            return Response({'detail': 'Email già in uso.'}, status=400)

        fornitore = User.objects.create_user(
            email=email, password=DEFAULT_FORNITORE_PASSWORD,
            cognome=request.data.get('cognome', ''), nome=nome,
            livello_accesso='fornitore',
            fornitore_ragione_sociale=ragione_sociale,
            telefono=telefono,
            indirizzo=indirizzo,
        )
        fornitore.raw_password = DEFAULT_FORNITORE_PASSWORD
        fornitore.save(update_fields=['raw_password'])
        data = EHSFornitoreSerializer(fornitore).data
        data['password_iniziale'] = DEFAULT_FORNITORE_PASSWORD
        return Response(data, status=201)


class EHSFornitoreDetailView(APIView):
    permission_classes = [IsAdminOrHO]

    def get_object(self, pk):
        return get_object_or_404(User, pk=pk, livello_accesso='fornitore')

    def patch(self, request, pk):
        fornitore = self.get_object(pk)
        for field in ('fornitore_ragione_sociale', 'cognome', 'nome', 'telefono', 'indirizzo'):
            if field in request.data:
                setattr(fornitore, field, (request.data.get(field) or '').strip())
        if 'email' in request.data:
            nuova_email = (request.data.get('email') or '').strip().lower()
            if nuova_email and User.objects.exclude(pk=fornitore.pk).filter(email=nuova_email).exists():
                return Response({'detail': 'Email già in uso.'}, status=400)
            fornitore.email = nuova_email
        fornitore.save()
        return Response(EHSFornitoreSerializer(fornitore).data)

    def delete(self, request, pk):
        fornitore = self.get_object(pk)
        fornitore.is_active = False
        fornitore.save(update_fields=['is_active'])
        return Response(status=204)


class EHSNotificaScadenzaView(APIView):
    """Popup minimale al primo accesso utile dello store destinatario (§8bis):
    corso, nome utente, data scadenza — generate dal job giornaliero (step 7)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.livello_accesso != 'store' or not user.store_id:
            return Response([])
        qs = EHSNotificaScadenza.objects.filter(
            negozio_destinatario=user.store, letta=False
        ).select_related('partecipante__utente', 'partecipante__sessione__corso').order_by('creata_il')
        return Response([
            {
                'id': n.id,
                'corso_nome': n.partecipante.sessione.corso.nome,
                'utente_nome': n.partecipante.utente.nome_completo,
                'scadenza_formazione': n.partecipante.scadenza_formazione,
            }
            for n in qs
        ])

    def patch(self, request, pk):
        try:
            n = EHSNotificaScadenza.objects.get(pk=pk, negozio_destinatario=request.user.store)
        except EHSNotificaScadenza.DoesNotExist:
            return Response(status=404)
        n.letta = True
        n.letta_il = timezone.now()
        n.save()
        return Response({'ok': True})


class EHSNotificaSessioneConfermataView(APIView):
    """Popup sulla home del fornitore quando una sua sessione viene confermata."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.livello_accesso != 'fornitore':
            return Response([])
        qs = EHSNotificaSessioneConfermata.objects.filter(
            fornitore=user, letta=False
        ).select_related('sessione__corso', 'sessione__negozio').order_by('creata_il')
        return Response([
            {
                'id': n.id,
                'corso_nome': n.sessione.corso.nome,
                'negozio_nome': str(n.sessione.negozio),
                'data_confermata': n.sessione.data_confermata,
            }
            for n in qs
        ])

    def patch(self, request, pk):
        try:
            n = EHSNotificaSessioneConfermata.objects.get(pk=pk, fornitore=request.user)
        except EHSNotificaSessioneConfermata.DoesNotExist:
            return Response(status=404)
        n.letta = True
        n.save(update_fields=['letta'])
        return Response({'ok': True})


class EHSNotificaNuovaRichiestaView(APIView):
    """Popup + pallino sulla home del fornitore quando gli arriva una nuova richiesta."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.livello_accesso != 'fornitore':
            return Response([])
        qs = EHSNotificaNuovaRichiesta.objects.filter(
            fornitore=user, letta=False
        ).select_related('sessione__corso', 'sessione__negozio').order_by('creata_il')
        return Response([
            {
                'id': n.id,
                'sessione_id': n.sessione_id,
                'corso_nome': n.sessione.corso.nome,
                'negozio_nome': str(n.sessione.negozio),
            }
            for n in qs
        ])

    def patch(self, request, pk):
        try:
            n = EHSNotificaNuovaRichiesta.objects.get(pk=pk, fornitore=request.user)
        except EHSNotificaNuovaRichiesta.DoesNotExist:
            return Response(status=404)
        n.letta = True
        n.save(update_fields=['letta'])
        return Response({'ok': True})


class EHSRegistriView(APIView):
    """Sezione 'Registri': sessioni completate con il relativo registro compilato,
    consultabile ma non scaricabile (vedi EHSRegistroFileView). Admin/HO vedono tutto
    e possono filtrare per negozio/fornitore/corso (query params: negozio, fornitore,
    corso) — necessario dato il volume su tutti i negozi/fornitori."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.livello_accesso not in RUOLI_EHS:
            return Response([])
        qs = (EHSSessione.objects.filter(stato='COMPLETATA')
              .exclude(registro_compilato_file='')
              .select_related('corso', 'negozio', 'fornitore')
              .prefetch_related('partecipanti__utente__store'))
        if user.livello_accesso == 'store':
            qs = qs.filter(negozio=user.store)
        elif user.livello_accesso == 'fornitore':
            qs = qs.filter(fornitore=user)
        elif user.livello_accesso in ('admin', 'ho'):
            params = request.query_params
            if params.get('negozio'):
                qs = qs.filter(negozio_id=params['negozio'])
            if params.get('fornitore'):
                qs = qs.filter(fornitore_id=params['fornitore'])
            if params.get('corso'):
                qs = qs.filter(corso_id=params['corso'])
        return Response([
            {
                'id': s.id,
                'corso_nome': s.corso.nome,
                'negozio_nome': str(s.negozio),
                'negozio_id': s.negozio_id,
                'data_confermata': s.data_confermata,
                'docente_nome': s.docente_nome,
                'fornitore_nome': s.fornitore.fornitore_ragione_sociale if s.fornitore else None,
                'fornitore_id': s.fornitore_id,
                'partecipanti_count': s.partecipanti.count(),
                'partecipanti': [
                    {'utente_nome': p.utente.nome_completo, 'presente': p.presente}
                    for p in s.partecipanti.all()
                ],
            }
            for s in qs.order_by('-data_confermata')
        ])


class EHSRegistroFileView(APIView):
    """Serve il registro compilato in streaming (mai un URL statico diretto): il
    frontend lo mostra inline (iframe da blob) senza esporre un link scaricabile."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        user = request.user
        sessione = get_object_or_404(EHSSessione, pk=pk, stato='COMPLETATA')
        autorizzato = user.livello_accesso in ('admin', 'ho') or (
            user.livello_accesso == 'store' and sessione.negozio_id == user.store_id
        ) or (user.livello_accesso == 'fornitore' and sessione.fornitore_id == user.id)
        if not autorizzato or not sessione.registro_compilato_file:
            return Response(status=404)
        return FileResponse(sessione.registro_compilato_file.open('rb'), content_type='application/pdf')
