import mimetypes
import random

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import generics
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from events.models import Evento
from stores.models import Store

from django.contrib.auth import get_user_model

from users.models import Role
from users.permissions import IsAdminEHS, IsAdminOrHOEHS

from . import services
from .models import (
    EHSAvviso,
    EHSConfigurazione,
    EHSCorso,
    EHSFormazione,
    EHSMansione,
    EHSNotificaDataProposta,
    EHSNotificaNuovaRichiesta,
    EHSNotificaScadenza,
    EHSNotificaSessioneConfermata,
    EHSNotificaSessioneConfermataStore,
    EHSObbligo,
    EHSPartecipante,
    EHSSessione,
)
from .serializers import (
    EHSCalendarioEventoSerializer,
    EHSCorsoSerializer,
    EHSFormazioneSerializer,
    EHSFornitoreSerializer,
    EHSMansioneSerializer,
    EHSObbligoSerializer,
    EHSPersonaSerializer,
    EHSSessioneDetailSerializer,
    EHSSessioneListSerializer,
)
from .services import TransizioneNonValida

User = get_user_model()

# Livelli con accesso alla sezione EHS (§4: la matrice permessi copre esplicitamente
# solo STORE/FORNITORE/ADMIN; HO è incluso per coerenza con il resto di Kollegas,
# dove è trattato quasi ovunque come equivalente ad ADMIN — vedi step 3).
RUOLI_EHS = ('store', 'fornitore', 'admin', 'admin_ehs', 'ho')


def _parse_data(value):
    if not value:
        return None
    dt = parse_datetime(value)
    return dt


def _genera_codice_corso():
    """Codice EHS + 4 cifre random, univoco. Il numero di combinazioni (10000) rende
    la collisione rara: si ritenta finché non se ne trova una libera."""
    while True:
        codice = f'EHS{random.randint(0, 9999):04d}'
        if not EHSCorso.objects.filter(codice=codice).exists():
            return codice


class EHSCorsoListCreateView(generics.ListCreateAPIView):
    """Catalogo dei corsi EHS selezionabili in 'Nuova Richiesta'. Store/fornitore
    vedono solo i corsi attivi (per la tendina); Admin/HO vedono anche quelli
    disattivati, per poterli gestire/riattivare dalla pagina di gestione."""
    serializer_class = EHSCorsoSerializer
    pagination_class = None  # il frontend si aspetta un array semplice, non paginato

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAdminOrHOEHS()]

    def get_queryset(self):
        user = self.request.user
        if user.livello_accesso not in RUOLI_EHS:
            return EHSCorso.objects.none()
        qs = EHSCorso.objects.prefetch_related('offerte__fornitore', 'offerte__negozi').order_by('nome')
        if user.livello_accesso not in ('admin', 'admin_ehs', 'ho'):
            qs = qs.filter(attivo=True)
        # ?richiedibili=1: solo i corsi con almeno un fornitore (tendina di 'Nuova Richiesta').
        if self.request.query_params.get('richiedibili'):
            qs = qs.filter(attivo=True, offerte__isnull=False).distinct()
        return qs

    def perform_create(self, serializer):
        serializer.save(codice=_genera_codice_corso())


class EHSCorsoDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = EHSCorsoSerializer
    queryset = EHSCorso.objects.prefetch_related('offerte__fornitore', 'offerte__negozi')
    permission_classes = [IsAdminOrHOEHS]

    def perform_destroy(self, instance):
        # Non elimina fisicamente: potrebbe essere referenziato da sessioni storiche.
        instance.attivo = False
        instance.save(update_fields=['attivo'])


class EHSCorsoFornitoriView(APIView):
    """GET /ehs/corsi/<pk>/fornitori/?negozio=<id> — fornitori che erogano il corso
    per il negozio ('idonei') e quelli richiedibili solo in via eccezionale. Per lo
    store il negozio è sempre il proprio."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        user = request.user
        if user.livello_accesso not in ('store', 'admin', 'admin_ehs', 'ho'):
            return Response({'detail': 'Non autorizzato.'}, status=403)
        corso = get_object_or_404(EHSCorso, pk=pk)
        if user.livello_accesso == 'store':
            negozio = user.store
        else:
            negozio_id = request.query_params.get('negozio')
            negozio = Store.objects.filter(pk=negozio_id).first() if negozio_id else None
        if negozio is None:
            return Response({'idonei': [], 'eccezionali': []})
        secondari = set(corso.offerte.filter(secondario=True).values_list('fornitore_id', flat=True))
        idonei = EHSFornitoreSerializer(services.fornitori_idonei(corso, negozio), many=True).data
        for f in idonei:
            f['secondario'] = f['id'] in secondari
        # I principali per primi: i secondari richiedono la validazione dell'EHS Admin.
        idonei.sort(key=lambda f: f['secondario'])
        return Response({
            'idonei': idonei,
            'eccezionali': EHSFornitoreSerializer(services.fornitori_eccezionali(corso, negozio), many=True).data,
        })


class EHSVerificaPartecipanteView(APIView):
    """GET /ehs/verifica-partecipante/?utente=<id>&corso=<id>[&evento=<id>] — dice se
    l'utente ha già questo corso valido (dal registro formazioni) e, se è indicato
    l'evento, se può iscriversi: un corso valido si rinnova solo negli ultimi
    GIORNI_RINNOVO_ANTICIPATO giorni prima della scadenza."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        utente_id = request.query_params.get('utente')
        corso_id = request.query_params.get('corso')
        if not utente_id or not corso_id:
            return Response({'valido': False})
        utente = get_object_or_404(User, pk=utente_id)
        corso = get_object_or_404(EHSCorso, pk=corso_id)
        f = services.ultima_formazione(utente, corso)
        oggi = timezone.now().date()
        if not f or (f.scadenza and f.scadenza < oggi):
            return Response({'valido': False})
        risposta = {'valido': True, 'corso_nome': corso.nome, 'scadenza_formazione': f.scadenza,
                    'rinnovabile_dal': services.rinnovabile_dal(f), 'bloccato': False}
        evento = Evento.objects.filter(pk=request.query_params.get('evento')).first() \
            if request.query_params.get('evento') else None
        if evento and risposta['rinnovabile_dal'] and evento.data < risposta['rinnovabile_dal']:
            risposta['bloccato'] = True
        return Response(risposta)


class EHSSessioneListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get_queryset_per_ruolo(self, user):
        qs = EHSSessione.objects.select_related('corso', 'negozio', 'fornitore', 'fornitore_richiesto', 'creata_da')
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
        if user.livello_accesso not in ('store', 'admin', 'admin_ehs', 'ho'):
            return Response({'detail': 'Non autorizzato.'}, status=403)

        corso_id = request.data.get('corso')
        contatto_nome = (request.data.get('contatto_negozio_nome') or '').strip()
        note = request.data.get('note', '')
        partecipanti_previsti = request.data.get('partecipanti_previsti') or None
        data_suggerita_store = _parse_data(request.data.get('data_suggerita_store'))

        if not corso_id or not contatto_nome:
            return Response({'detail': 'Corso e contatto negozio sono obbligatori.'}, status=400)

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

        # Il fornitore va scelto tra quelli che erogano il corso per il negozio (se è
        # uno solo viene assegnato in automatico); con 'eccezionale' può essere un
        # fornitore fuori perimetro, e la richiesta passa prima dall'EHS Admin.
        fornitore = None
        fornitore_id = request.data.get('fornitore')
        if fornitore_id:
            fornitore = get_object_or_404(User, pk=fornitore_id, livello_accesso='fornitore')
        eccezionale = str(request.data.get('eccezionale', '')).lower() in ('true', '1', 'on')

        try:
            sessione = services.crea_richiesta(
                user, corso, negozio, contatto_nome, '', note, fornitore=fornitore,
                partecipanti_previsti=partecipanti_previsti, data_suggerita_store=data_suggerita_store,
                modalita=request.data.get('modalita') or 'PRESENZA',
                eccezionale=eccezionale,
                motivazione_eccezione=request.data.get('motivazione_eccezione') or '',
            )
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=400)
        return Response(EHSSessioneDetailSerializer(sessione, context={'request': request}).data, status=201)


class BaseEHSSessioneActionView(APIView):
    """Base comune alle azioni sulla macchina a stati: recupera la sessione applicando
    la stessa visibilità per ruolo della lista (§4), senza duplicare la logica."""
    permission_classes = [IsAuthenticated]

    def get_sessione_visibile(self, request, pk):
        user = request.user
        qs = EHSSessioneListCreateView().get_queryset_per_ruolo(user)
        if user.livello_accesso in ('admin', 'admin_ehs', 'ho'):
            qs = EHSSessione.objects.select_related('corso', 'negozio', 'fornitore', 'fornitore_richiesto', 'creata_da')
        return get_object_or_404(qs, pk=pk)

    def risposta(self, request, sessione):
        return Response(EHSSessioneDetailSerializer(sessione, context={'request': request}).data)

    def esegui(self, request, pk, azione, status_errore=403):
        """Recupera la sessione visibile, applica l'azione di servizio e risponde
        con il dettaglio aggiornato (o con l'errore della macchina a stati)."""
        sessione = self.get_sessione_visibile(request, pk)
        try:
            sessione = azione(sessione) or sessione
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=status_errore)
        sessione.refresh_from_db()
        return self.risposta(request, sessione)


class EHSSessioneDetailView(BaseEHSSessioneActionView):
    def get(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        return self.risposta(request, sessione)


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
        link_online = request.data.get('link_online')
        link_online = link_online.strip() if isinstance(link_online, str) else None
        try:
            sessione = services.proponi_data(sessione, request.user, data_proposta, docente_nome, docente_telefono,
                                             link_online=link_online,
                                             partecipanti_min=request.data.get('partecipanti_min'),
                                             partecipanti_max=request.data.get('partecipanti_max'))
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return self.risposta(request, sessione)


class EHSRispondiDataView(BaseEHSSessioneActionView):
    def patch(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        accetta = bool(request.data.get('accetta'))
        nuova_data = _parse_data(request.data.get('nuova_data'))
        try:
            sessione = services.rispondi_data(sessione, request.user, accetta, nuova_data)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return self.risposta(request, sessione)


class EHSAccettaContropropostaView(BaseEHSSessioneActionView):
    """Il fornitore accetta così com'è la data contro-proposta dallo store."""
    def patch(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        try:
            sessione = services.accetta_controproposta(sessione, request.user)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return self.risposta(request, sessione)


class EHSChiudiAulaView(BaseEHSSessioneActionView):
    """Ultimo passaggio del wizard 'Aula completata': un solo submit multipart con
    le presenze per partecipante ('presente_<id>' bool, 'motivo_<id>' opzionale per
    gli assenti) e uno o più documenti di chiusura ('files', ripetuto)."""
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        files = request.FILES.getlist('files') or request.FILES.getlist('file')
        presenze, assenze_motivo = {}, {}
        for p in sessione.partecipanti.all():
            presenze[p.id] = str(request.data.get(f'presente_{p.id}', '')).lower() in ('true', '1', 'on')
            motivo = request.data.get(f'motivo_{p.id}')
            if motivo:
                assenze_motivo[p.id] = motivo
        try:
            sessione = services.chiudi_aula(sessione, presenze, files, request.user, assenze_motivo)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return self.risposta(request, sessione)


class EHSAssegnaFornitoreView(BaseEHSSessioneActionView):
    """Assegna un fornitore idoneo a una richiesta ancora senza fornitore o rimasta
    senza fornitore disponibile (store o Admin/HO) — necessario perché un fornitore
    vede solo le proprie sessioni: senza assegnazione nessuno riceverebbe la richiesta."""
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
        return self.risposta(request, sessione)


class EHSAnnullaView(BaseEHSSessioneActionView):
    def patch(self, request, pk):
        sessione = self.get_sessione_visibile(request, pk)
        try:
            sessione = services.annulla_sessione(sessione, request.user)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=400)
        return self.risposta(request, sessione)


class EHSNonDisponibileView(BaseEHSSessioneActionView):
    """Il fornitore segnala di non poter erogare la formazione richiesta."""
    def patch(self, request, pk):
        motivo = (request.data.get('motivo') or '').strip()
        return self.esegui(request, pk, lambda s: services.dichiara_non_disponibile(s, request.user, motivo))


class EHSRichiestaEccezionaleView(BaseEHSSessioneActionView):
    """Lo store chiede un fornitore fuori dal proprio perimetro (da approvare EHS Admin)."""
    def patch(self, request, pk):
        fornitore_id = request.data.get('fornitore')
        if not fornitore_id:
            return Response({'detail': 'fornitore obbligatorio.'}, status=400)
        fornitore = get_object_or_404(User, pk=fornitore_id, livello_accesso='fornitore')
        motivazione = request.data.get('motivazione') or ''
        return self.esegui(request, pk, lambda s: services.richiedi_eccezione(s, request.user, fornitore, motivazione))


class EHSDecidiEccezioneView(BaseEHSSessioneActionView):
    """L'EHS Admin approva ('approva': true) o rifiuta una richiesta eccezionale."""
    def patch(self, request, pk):
        approva = bool(request.data.get('approva'))
        nota = (request.data.get('nota') or '').strip()
        return self.esegui(request, pk, lambda s: services.decidi_eccezione(s, request.user, approva, nota))


class EHSLinkOnlineView(BaseEHSSessioneActionView):
    def patch(self, request, pk):
        link = (request.data.get('link_online') or '').strip()
        return self.esegui(request, pk, lambda s: services.aggiorna_link_online(s, request.user, link))


class EHSRimuoviPartecipanteView(BaseEHSSessioneActionView):
    """DELETE /ehs/sessioni/<pk>/partecipanti/<partecipante_id>/ — cancella l'iscrizione
    (store, fornitore o Admin), fino a 7 giorni prima della formazione."""
    def delete(self, request, pk, partecipante_id):
        sessione = self.get_sessione_visibile(request, pk)
        partecipante = get_object_or_404(EHSPartecipante.objects.select_related('utente'),
                                         pk=partecipante_id, sessione=sessione)
        try:
            services.rimuovi_partecipante(sessione, partecipante, request.user)
        except TransizioneNonValida as e:
            return Response({'detail': str(e)}, status=403)
        return self.risposta(request, sessione)


class EHSAttestatiCaricatiView(BaseEHSSessioneActionView):
    """Il fornitore conferma di aver caricato gli attestati su SharePoint."""
    def patch(self, request, pk):
        return self.esegui(request, pk, lambda s: services.segna_attestati_caricati(s, request.user))


class EHSCalendarioView(APIView):
    """GET /api/ehs/calendario/ — eventi del calendario principale (EHS e non, §5.6:
    'restano visibili in sola lettura tutti gli altri eventi'), nessun filtro per
    negozio: stessa visibilità del calendario Kollegas esistente (che oggi non
    restringe per store neanche per il ruolo store — vedi EventoListCreateView).
    Il fornitore vede in chiaro solo le proprie sessioni: ogni altra attività, in
    qualunque store, gli appare solo come 'Occupato' con il nome dello store."""
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
        qs = qs.order_by('data', 'ora_inizio')
        if request.user.livello_accesso != 'fornitore':
            return Response(EHSCalendarioEventoSerializer(qs, many=True).data)

        risultato = []
        for ev in qs:
            sessione = getattr(ev, 'ehs_sessione', None) if ev.is_ehs else None
            if sessione and sessione.fornitore_id == request.user.id:
                risultato.append(EHSCalendarioEventoSerializer(ev).data)
            else:
                risultato.append(self._occupato(ev))
        return Response(risultato)

    @staticmethod
    def _occupato(ev):
        return {
            'id': ev.id, 'data': ev.data, 'ora_inizio': ev.ora_inizio, 'ora_fine': ev.ora_fine,
            'attivita_nome': 'Occupato', 'attivita_tipologia': 'altro',
            'location_display': ev.location_store.nome if ev.location_store else '',
            'max_partecipanti': 0, 'iscritti_count': 0, 'posti_disponibili': None,
            'is_ehs': False, 'ehs_luogo': '', 'ehs_sessione_id': None, 'ehs_sessione_stato': None,
            'ehs_corso_nome': None, 'ehs_negozio_codice': None, 'occupato': True,
        }


DEFAULT_FORNITORE_PASSWORD = 'Primark01!'


class EHSFornitoreListCreateView(APIView):
    """Anagrafica fornitori EHS: gestita solo da Admin/HO, ma leggibile anche da
    Store/Fornitore (serve per il menù a tendina nella nuova richiesta)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.livello_accesso not in RUOLI_EHS:
            return Response([])
        qs = User.objects.filter(livello_accesso='fornitore')
        if request.user.livello_accesso not in ('admin', 'admin_ehs', 'ho'):
            qs = qs.filter(is_active=True)
        return Response(EHSFornitoreSerializer(qs.order_by('fornitore_ragione_sociale'), many=True).data)

    def post(self, request):
        if request.user.livello_accesso not in ('admin', 'admin_ehs', 'ho'):
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
    permission_classes = [IsAdminOrHOEHS]

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
        ).select_related(
            'formazione__utente', 'formazione__corso', 'partecipante__utente', 'partecipante__sessione__corso',
        ).order_by('creata_il')
        risultato = []
        for n in qs:
            if n.formazione:
                corso, utente, scadenza = n.formazione.corso, n.formazione.utente, n.formazione.scadenza
            else:  # notifiche generate prima del registro formazioni
                corso, utente, scadenza = n.partecipante.sessione.corso, n.partecipante.utente, n.partecipante.scadenza_formazione
            risultato.append({
                'id': n.id, 'corso_nome': corso.nome, 'utente_nome': utente.nome_completo,
                'scadenza_formazione': scadenza,
            })
        return Response(risultato)

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


class EHSNotificaSessioneConfermataStoreView(APIView):
    """Popup sulla home dello store quando una sua sessione viene confermata
    dall'accettazione del fornitore (contro-proposta accettata)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.livello_accesso != 'store' or not user.store_id:
            return Response([])
        qs = EHSNotificaSessioneConfermataStore.objects.filter(
            negozio_destinatario=user.store, letta=False
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
            n = EHSNotificaSessioneConfermataStore.objects.get(pk=pk, negozio_destinatario=request.user.store)
        except EHSNotificaSessioneConfermataStore.DoesNotExist:
            return Response(status=404)
        n.letta = True
        n.save(update_fields=['letta'])
        return Response({'ok': True})


class EHSNotificaDataPropostaView(APIView):
    """Popup sulla home dello store quando il fornitore propone (o ripropone) una data."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.livello_accesso != 'store' or not user.store_id:
            return Response([])
        qs = EHSNotificaDataProposta.objects.filter(
            negozio_destinatario=user.store, letta=False
        ).select_related('sessione__corso', 'sessione__negozio', 'sessione__fornitore').order_by('creata_il')
        return Response([
            {
                'id': n.id,
                'sessione_id': n.sessione_id,
                'corso_nome': n.sessione.corso.nome,
                'negozio_nome': str(n.sessione.negozio),
                'data_proposta': n.sessione.data_proposta,
                'fornitore_nome': (
                    n.sessione.fornitore.fornitore_ragione_sociale or n.sessione.fornitore.nome_completo
                ) if n.sessione.fornitore else None,
            }
            for n in qs
        ])

    def patch(self, request, pk):
        try:
            n = EHSNotificaDataProposta.objects.get(pk=pk, negozio_destinatario=request.user.store)
        except EHSNotificaDataProposta.DoesNotExist:
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
    """Sezione 'Registri': sessioni completate con i relativi documenti di chiusura,
    consultabile ma non scaricabile (vedi EHSRegistroFileView). Admin/HO vedono tutto
    e possono filtrare per negozio/fornitore/corso (query params: negozio, fornitore,
    corso) — necessario dato il volume su tutti i negozi/fornitori."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.livello_accesso not in RUOLI_EHS:
            return Response([])
        qs = (EHSSessione.objects.filter(stato='COMPLETATA')
              .select_related('corso', 'negozio', 'fornitore')
              .prefetch_related('partecipanti__utente__store', 'documenti'))
        if user.livello_accesso == 'store':
            qs = qs.filter(negozio=user.store)
        elif user.livello_accesso == 'fornitore':
            qs = qs.filter(fornitore=user)
        elif user.livello_accesso in ('admin', 'admin_ehs', 'ho'):
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
                'documenti': [{'id': d.id, 'nome_originale': d.nome_originale} for d in s.documenti.all()],
                'attestati_caricati_il': s.attestati_caricati_il,
            }
            for s in qs.order_by('-data_confermata')
        ])


class EHSRegistroDeleteView(APIView):
    """DELETE /ehs/registri/<pk>/ — elimina definitivamente l'intera sessione EHS
    completata (documenti di chiusura, presenze, evento sul calendario collegato e
    relative iscrizioni). Azione irreversibile, riservata ad Admin e Admin EHS:
    richiede la conferma testuale esatta 'ELIMINARE DEFINITIVAMENTE' nel body."""
    permission_classes = [IsAdminEHS]

    def delete(self, request, pk):
        sessione = get_object_or_404(EHSSessione, pk=pk, stato='COMPLETATA')
        conferma = (request.data.get('conferma') or '').strip()
        if conferma != 'ELIMINARE DEFINITIVAMENTE':
            return Response({'detail': 'Conferma non valida.'}, status=400)

        for doc in sessione.documenti.all():
            doc.file.delete(save=False)
        if sessione.calendario_evento_id:
            from participants.models import Iscrizione
            Iscrizione.objects.filter(evento_id=sessione.calendario_evento_id).delete()
            sessione.calendario_evento.delete()
        sessione.delete()
        return Response(status=204)


class EHSRegistroFileView(APIView):
    """Serve un documento di chiusura in streaming (mai un URL statico diretto): il
    frontend lo mostra inline (iframe da blob) senza esporre un link scaricabile.
    Senza documento_id serve il primo documento della sessione."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, documento_id=None):
        user = request.user
        sessione = get_object_or_404(EHSSessione, pk=pk, stato='COMPLETATA')
        autorizzato = user.livello_accesso in ('admin', 'admin_ehs', 'ho') or (
            user.livello_accesso == 'store' and sessione.negozio_id == user.store_id
        ) or (user.livello_accesso == 'fornitore' and sessione.fornitore_id == user.id)
        if not autorizzato:
            return Response(status=404)
        docs = sessione.documenti.all()
        doc = docs.filter(pk=documento_id).first() if documento_id else docs.first()
        if not doc:
            return Response(status=404)
        content_type = mimetypes.guess_type(doc.nome_originale or doc.file.name)[0] or 'application/octet-stream'
        return FileResponse(doc.file.open('rb'), content_type=content_type)


class EHSScadenzeView(APIView):
    """Pannello 'Alert scadenze': formazioni che scadono entro 45 giorni (o già
    scadute) con il countdown. Lo store vede i collaboratori in forza nel proprio
    negozio; Admin/HO tutti, con filtro opzionale ?negozio=<id>."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.livello_accesso == 'store':
            if not user.store_id:
                return Response([])
            negozio = user.store
        elif user.livello_accesso in ('admin', 'admin_ehs', 'ho'):
            negozio_id = request.query_params.get('negozio')
            negozio = get_object_or_404(Store, pk=negozio_id) if negozio_id else None
        else:
            return Response([])
        return Response(services.scadenze_in_arrivo(negozio=negozio))


class EHSConfigurazioneView(APIView):
    """Impostazioni globali EHS (link alla cartella SharePoint degli attestati):
    leggibili da tutti i ruoli EHS, modificabili solo da Admin/EHS Admin."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.livello_accesso not in RUOLI_EHS:
            return Response(status=403)
        config = EHSConfigurazione.get()
        return Response({'sharepoint_attestati_url': config.sharepoint_attestati_url})

    def patch(self, request):
        if request.user.livello_accesso not in ('admin', 'admin_ehs'):
            return Response({'detail': 'Solo Admin/EHS Admin possono modificare la configurazione EHS.'}, status=403)
        url = (request.data.get('sharepoint_attestati_url') or '').strip()
        if url and not url.lower().startswith('https://'):
            return Response({'detail': 'Il link deve iniziare con https://'}, status=400)
        config = EHSConfigurazione.get()
        config.sharepoint_attestati_url = url
        config.save()
        return Response({'sharepoint_attestati_url': config.sharepoint_attestati_url})


# --- Formazione obbligatoria ----------------------------------------------------

# Chi può consultare matrice e registro: Area e Store compresi (lo store solo per il
# proprio negozio). Le modifiche alla matrice sono riservate ad Admin/EHS Admin.
RUOLI_LETTURA_OBBLIGHI = ('admin', 'admin_ehs', 'ho', 'area', 'store')


def _negozio_consentito(request, negozio_id):
    """Negozio richiesto se l'utente può vederlo: lo store vede solo il proprio."""
    user = request.user
    if user.livello_accesso == 'store':
        return user.store
    if user.livello_accesso in RUOLI_LETTURA_OBBLIGHI and negozio_id:
        return Store.objects.filter(pk=negozio_id).first()
    return None


class EHSMatriceView(APIView):
    """GET /ehs/matrice/ — matrice obblighi completa (corsi, ruoli, mansioni, celle).
    PUT /ehs/matrice/ {corso, ruolo|mansione, stato} — imposta una cella:
    stato 'obbligatorio', 'facoltativo' o null per toglierla."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # La matrice "cosa deve fare chi" è consultabile da tutti gli utenti.
        return Response({
            'corsi': EHSCorsoSerializer(EHSCorso.objects.filter(attivo=True).order_by('nome'), many=True).data,
            'ruoli': [{'id': r.id, 'nome': r.nome} for r in
                      Role.objects.exclude(nome__in=services.RUOLI_ESCLUSI_OBBLIGHI).order_by('nome')],
            'mansioni': EHSMansioneSerializer(EHSMansione.objects.filter(attivo=True), many=True).data,
            'obblighi': EHSObbligoSerializer(EHSObbligo.objects.all(), many=True).data,
        })

    def put(self, request):
        if request.user.livello_accesso not in ('admin', 'admin_ehs'):
            return Response({'detail': 'Solo Admin/EHS Admin possono modificare la matrice.'}, status=403)
        corso = get_object_or_404(EHSCorso, pk=request.data.get('corso'))
        ruolo_id, mansione_id = request.data.get('ruolo'), request.data.get('mansione')
        if bool(ruolo_id) == bool(mansione_id):
            return Response({'detail': 'Indicare un ruolo oppure una mansione.'}, status=400)
        stato = request.data.get('stato')
        if stato not in ('obbligatorio', 'facoltativo', None):
            return Response({'detail': 'Stato non valido.'}, status=400)
        obbligo = services.imposta_cella_matrice(
            corso,
            ruolo=get_object_or_404(Role, pk=ruolo_id) if ruolo_id else None,
            mansione=get_object_or_404(EHSMansione, pk=mansione_id) if mansione_id else None,
            stato=stato,
        )
        return Response(EHSObbligoSerializer(obbligo).data if obbligo else None)


class EHSMansioneListCreateView(generics.ListCreateAPIView):
    serializer_class = EHSMansioneSerializer
    pagination_class = None
    queryset = EHSMansione.objects.all()

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAdminEHS()]


class EHSPersoneView(APIView):
    """GET /ehs/persone/?negozio=<id> — persone del negozio soggette alla matrice,
    con mansioni e registro formazioni."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        negozio = _negozio_consentito(request, request.query_params.get('negozio'))
        if negozio is None:
            return Response([])
        persone = services.persone_monitorate(negozio).prefetch_related('ehs_formazioni__corso')
        return Response(EHSPersonaSerializer(persone, many=True).data)


class EHSPersonaMansioniView(APIView):
    """PUT /ehs/persone/<pk>/mansioni/ {mansioni: [id]} — Admin/EHS Admin per tutti,
    lo store per i collaboratori del proprio negozio."""
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        user = request.user
        persona = get_object_or_404(User, pk=pk)
        consentito = (user.livello_accesso in ('admin', 'admin_ehs')
                      or (user.livello_accesso == 'store' and user.store_id and persona.store_id == user.store_id))
        if not consentito:
            return Response({'detail': 'Non autorizzato.'}, status=403)
        mansioni = EHSMansione.objects.filter(pk__in=request.data.get('mansioni') or [])
        persona.ehs_mansioni.set(mansioni)
        return Response({'id': persona.id, 'mansioni': [m.id for m in mansioni]})


class EHSFormazioneCreateView(generics.CreateAPIView):
    """Inserimento manuale nel registro (formazioni svolte fuori dalle aule EHS)."""
    serializer_class = EHSFormazioneSerializer
    permission_classes = [IsAdminEHS]

    def perform_create(self, serializer):
        serializer.save(fonte='manuale', creata_da=self.request.user)


class EHSFormazioneDetailView(generics.DestroyAPIView):
    queryset = EHSFormazione.objects.all()
    permission_classes = [IsAdminEHS]


class EHSCompletamentoView(APIView):
    """GET /ehs/completamento/ — % di completamento della formazione obbligatoria per
    Italia, area e negozio (Admin, EHS Admin, HO, Area)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.livello_accesso not in ('admin', 'admin_ehs', 'ho', 'area'):
            return Response(status=403)
        return Response(services.completamento_obbligatori())


class EHSCompletamentoNegozioView(APIView):
    """GET /ehs/completamento/negozio/<pk>/ — semaforo persona × corso del negozio.
    Lo store vede solo il proprio."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        negozio = _negozio_consentito(request, pk)
        if negozio is None or negozio.pk != pk:
            return Response(status=403)
        return Response(services.completamento_negozio(negozio))


class EHSCercaFormazioniView(APIView):
    """GET /ehs/cerca-formazioni/ — aule confermate ancora da svolgere, di tutti i negozi,
    con filtri: corso, negozio, citta, dal, al (YYYY-MM-DD), modalita, solo_posti=1.
    Serve allo store per trovare un'aula a cui iscrivere i propri collaboratori senza
    scorrere il calendario mese per mese. Il fornitore vede solo le proprie."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.livello_accesso not in RUOLI_EHS:
            return Response([])
        qs = (EHSSessione.objects.filter(stato='CONFERMATA', data_confermata__gte=timezone.now())
              .select_related('corso', 'negozio', 'fornitore').order_by('data_confermata'))
        if user.livello_accesso == 'fornitore':
            qs = qs.filter(fornitore=user)
        p = request.query_params
        if p.get('corso'):
            qs = qs.filter(corso_id=p['corso'])
        if p.get('negozio'):
            qs = qs.filter(negozio_id=p['negozio'])
        if p.get('citta'):
            qs = qs.filter(negozio__comune__icontains=p['citta'].strip())
        if p.get('dal'):
            qs = qs.filter(data_confermata__date__gte=p['dal'])
        if p.get('al'):
            qs = qs.filter(data_confermata__date__lte=p['al'])
        if p.get('modalita') in ('PRESENZA', 'ONLINE'):
            qs = qs.filter(modalita=p['modalita'])
        risultato = []
        for s in qs:
            iscritti = s.partecipanti.count()
            posti = s.partecipanti_max - iscritti if s.partecipanti_max else None
            if p.get('solo_posti') == '1' and posti is not None and posti <= 0:
                continue
            risultato.append({
                'id': s.id, 'corso_id': s.corso_id, 'corso_nome': s.corso.nome,
                'negozio_id': s.negozio_id, 'negozio_nome': s.negozio.nome, 'negozio_comune': s.negozio.comune,
                'data': s.data_confermata, 'durata_ore': s.durata_ore, 'modalita': s.modalita,
                'iscritti': iscritti, 'minimo': services.minimo_partecipanti(s), 'massimo': s.partecipanti_max,
                'posti_liberi': posti, 'evento_id': s.calendario_evento_id,
                'mio_negozio': user.livello_accesso == 'store' and s.negozio_id == user.store_id,
            })
        return Response(risultato)


class EHSAvvisoView(APIView):
    """GET /ehs/avvisi/ — avvisi non letti (minimo partecipanti, annullamenti automatici):
    lo store riceve quelli del proprio negozio, fornitore ed EHS Admin i propri.
    PATCH /ehs/avvisi/<pk>/ — segna come letto."""
    permission_classes = [IsAuthenticated]

    def _qs(self, user):
        from django.db.models import Q
        filtro = Q(utente=user)
        if user.livello_accesso == 'store' and user.store_id:
            filtro |= Q(negozio_id=user.store_id)
        return EHSAvviso.objects.filter(filtro, letta=False).select_related('sessione__corso', 'sessione__negozio')

    def get(self, request):
        return Response([
            {'id': a.id, 'tipo': a.tipo, 'testo': a.testo, 'sessione_id': a.sessione_id,
             'corso_nome': a.sessione.corso.nome, 'negozio_nome': a.sessione.negozio.nome, 'creata_il': a.creata_il}
            for a in self._qs(request.user)
        ])

    def patch(self, request, pk):
        avviso = get_object_or_404(self._qs(request.user), pk=pk)
        avviso.letta = True
        avviso.save(update_fields=['letta'])
        return Response({'ok': True})
