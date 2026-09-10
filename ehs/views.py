from django.db.models import Q
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
from .models import EHSCorso, EHSNotificaScadenza, EHSSessione
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
            # Vede le proprie sessioni + quelle non ancora assegnate a nessun fornitore
            # (per poterle prendere in carico proponendo una data).
            qs = qs.filter(Q(fornitore=user) | Q(fornitore__isnull=True))
            if user.negozi_abilitati.exists():
                qs = qs.filter(negozio__in=user.negozi_abilitati.all())
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
                user, corso, negozio, contatto_nome, contatto_telefono, note, fornitore=fornitore
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
        if not data_proposta:
            return Response({'detail': 'data_proposta obbligatoria (ISO datetime).'}, status=400)
        try:
            sessione = services.proponi_data(sessione, request.user, data_proposta)
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


class EHSConfermaView(BaseEHSSessioneActionView):
    def patch(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        docente_nome = (request.data.get('docente_nome') or '').strip()
        docente_telefono = (request.data.get('docente_telefono') or '').strip()
        if not docente_nome:
            return Response({'detail': 'docente_nome obbligatorio.'}, status=400)
        try:
            sessione = services.conferma(sessione, request.user, docente_nome, docente_telefono)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return Response(EHSSessioneDetailSerializer(sessione).data)


class EHSRegistroView(BaseEHSSessioneActionView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        file = request.FILES.get('file')
        if not file:
            return Response({'detail': 'File obbligatorio.'}, status=400)
        try:
            sessione = services.carica_registro(sessione, request.user, file)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return Response(EHSSessioneDetailSerializer(sessione).data)


class EHSRegistroCompilatoView(BaseEHSSessioneActionView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        file = request.FILES.get('file')
        if not file:
            return Response({'detail': 'File obbligatorio.'}, status=400)
        try:
            sessione = services.carica_registro_compilato(sessione, request.user, file)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return Response(EHSSessioneDetailSerializer(sessione).data)


class EHSChiudiAulaView(BaseEHSSessioneActionView):
    """Un solo submit multipart (§5bis): per ogni partecipante <id> arrivano i campi
    'presente_<id>' (bool), 'attestato_<id>' (file, opzionale) e 'motivo_<id>' (opzionale)."""
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        presenze, attestati, assenze_motivo = {}, {}, {}
        for p in sessione.partecipanti.all():
            presenze[p.id] = str(request.data.get(f'presente_{p.id}', '')).lower() in ('true', '1', 'on')
            attestato = request.FILES.get(f'attestato_{p.id}')
            if attestato:
                attestati[p.id] = attestato
            motivo = request.data.get(f'motivo_{p.id}')
            if motivo:
                assenze_motivo[p.id] = motivo
        try:
            sessione = services.chiudi_aula(sessione, presenze, attestati, assenze_motivo, request.user)
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
        qs = Evento.objects.select_related('attivita', 'location_store').prefetch_related('iscrizioni')
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
        if not email or not ragione_sociale or not nome:
            return Response({'detail': 'Email, nome azienda e nome di riferimento sono obbligatori.'}, status=400)

        if User.objects.filter(email=email).exists():
            return Response({'detail': 'Email già in uso.'}, status=400)

        fornitore = User.objects.create_user(
            email=email, password=DEFAULT_FORNITORE_PASSWORD,
            cognome=request.data.get('cognome', ''), nome=nome,
            livello_accesso='fornitore',
            fornitore_ragione_sociale=ragione_sociale,
            telefono=(request.data.get('telefono') or '').strip(),
            indirizzo=(request.data.get('indirizzo') or '').strip(),
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
