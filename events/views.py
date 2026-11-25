from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers as drf_serializers
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import Host, AttivitaCatalogo, Evento, EccezioneCalendario, NotificaEvento, RichiestaDisattivazioneAttivita
from .serializers import (
    HostSerializer, AttivitaCatalogoSerializer, EventoListSerializer, EventoDetailSerializer,
    RichiestaDisattivazioneAttivitaSerializer,
)
from users.accesso import MESSAGGIO_SOLA_VISIONE_EHS, sola_visione_ehs
from users.permissions import IsAdmin, IsAdminOrHO,IsAdminOrHOEHS, IsAdminOrHOOrArea, IsAdminOrHOOrAreaEHS


class HostListCreateView(generics.ListCreateAPIView):
    serializer_class = HostSerializer
    pagination_class = None  # elenco completo per tendine e gestione
    queryset = Host.objects.filter(is_active=True)

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAdminOrHOOrArea()]


class HostDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = HostSerializer
    queryset = Host.objects.all()

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAdminOrHOOrArea()]


class AttivitaCatalogoListCreateView(generics.ListCreateAPIView):
    """Catalogo attività: di default solo quelle attive (tendine, nuovi eventi).
    ?tutte=1 include le disattivate (filtri di Stats ed Elenco Attività: lo storico
    resta consultabile); ?disattivate=1 solo le disattivate (sezione Corsi disattivati)."""
    serializer_class = AttivitaCatalogoSerializer
    pagination_class = None  # elenco completo: oltre 50 voci la paginazione nascondeva attività

    def get_queryset(self):
        from django.db.models import Exists, OuterRef
        in_attesa = RichiestaDisattivazioneAttivita.objects.filter(attivita=OuterRef('pk'), stato='pending')
        qs = AttivitaCatalogo.objects.prefetch_related('ruoli_destinatari').annotate(disattivazione_in_attesa=Exists(in_attesa))
        params = self.request.query_params
        if params.get('disattivate'):
            return qs.filter(is_active=False)
        if params.get('tutte'):
            return qs
        return qs.filter(is_active=True)

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAdminOrHOOrArea()]


class AttivitaCatalogoDetailView(generics.RetrieveUpdateDestroyAPIView):
    """DELETE non elimina: disattiva l'attività (solo Admin). Eventi, iscrizioni e
    statistiche già registrati restano intatti; si riattiva con PATCH is_active=true."""
    serializer_class = AttivitaCatalogoSerializer
    queryset = AttivitaCatalogo.objects.all()

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        if self.request.method == 'DELETE' or 'is_active' in self.request.data:
            return [IsAdmin()]
        return [IsAdminOrHOOrArea()]

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active'])
        _chiudi_richieste_disattivazione(instance, self.request.user)


def _chiudi_richieste_disattivazione(attivita, admin, stato='approvata'):
    RichiestaDisattivazioneAttivita.objects.filter(attivita=attivita, stato='pending').update(
        stato=stato, processed_by=admin, processed_at=timezone.now())


class RichiediDisattivazioneAttivitaView(APIView):
    """POST /attivita/<pk>/richiedi-disattivazione/ — l'HO chiede la disattivazione:
    l'attività resta attiva finché l'Admin non approva."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.livello_accesso != 'ho':
            return Response({'detail': 'Solo gli HO inviano la richiesta: l\'Admin disattiva direttamente.'}, status=403)
        attivita = get_object_or_404(AttivitaCatalogo, pk=pk, is_active=True)
        richiesta, creata = RichiestaDisattivazioneAttivita.objects.get_or_create(
            attivita=attivita, stato='pending', defaults={'richiedente': request.user})
        if not creata:
            return Response({'detail': 'Disattivazione già in attesa di approvazione.'}, status=400)
        return Response(RichiestaDisattivazioneAttivitaSerializer(richiesta).data, status=201)


class RichiesteDisattivazioneAttivitaView(APIView):
    """GET — richieste in attesa (solo Admin)."""
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = RichiestaDisattivazioneAttivita.objects.filter(stato='pending').select_related('attivita', 'richiedente')
        return Response(RichiestaDisattivazioneAttivitaSerializer(qs, many=True).data)


class RichiestaDisattivazioneAttivitaDetailView(APIView):
    """POST {azione: 'approva'|'rifiuta'} — con 'approva' l'attività viene disattivata."""
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        richiesta = get_object_or_404(RichiestaDisattivazioneAttivita.objects.select_related('attivita'),
                                      pk=pk, stato='pending')
        azione = request.data.get('azione')
        if azione not in ('approva', 'rifiuta'):
            return Response({'detail': 'Azione non valida.'}, status=400)
        if azione == 'approva':
            richiesta.attivita.is_active = False
            richiesta.attivita.save(update_fields=['is_active'])
        _chiudi_richieste_disattivazione(richiesta.attivita, request.user,
                                         'approvata' if azione == 'approva' else 'rifiutata')
        return Response({'ok': True})


class EventoListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    filter_backends = [OrderingFilter]
    ordering_fields = ['data', 'ora_inizio']
    ordering = ['data', 'ora_inizio']

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return EventoDetailSerializer
        return EventoListSerializer

    def get_queryset(self):
        qs = Evento.objects.select_related(
            'attivita', 'host', 'location_store', 'ehs_sessione__corso', 'ehs_sessione__negozio',
        ).prefetch_related('iscrizioni')
        params = self.request.query_params
        if params.get('anno') and params.get('mese'):
            qs = qs.filter(data__year=params['anno'], data__month=params['mese'])
        if params.get('data_da'):
            qs = qs.filter(data__gte=params['data_da'])
        if params.get('data_a'):
            qs = qs.filter(data__lte=params['data_a'])
        if params.get('attivita'):
            qs = qs.filter(attivita_id=params['attivita'])
        if params.get('tipologia'):
            qs = qs.filter(attivita__tipologia=params['tipologia'])
        if params.get('location_store'):
            qs = qs.filter(location_store_id=params['location_store'])
        return qs

    def get_permissions(self):
        if self.request.method == 'POST':
            # L'utente Area visualizza soltanto: non crea formazioni.
            return [IsAdminOrHOEHS()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        dati = serializer.validated_data
        if sola_visione_ehs(self.request.user) and (dati.get('is_ehs') or dati['attivita'].tipologia == 'ehs'):
            self.permission_denied(self.request, message=MESSAGGIO_SOLA_VISIONE_EHS)
        super().perform_create(serializer)
        actor = self.request.user
        if actor.livello_accesso in ('admin', 'admin_ehs', 'ho'):
            evento = serializer.instance
            location = evento.location_store.nome if evento.location_store else evento.location_esterna or '—'
            notifica = NotificaEvento.objects.create(
                snap_attivita_nome=evento.attivita.nome,
                snap_data=evento.data,
                snap_location=location,
                snap_creato_da=f'{actor.cognome} {actor.nome}',
            )
            notifica.letta_da.add(actor)


class NotificaEventoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.livello_accesso not in ('store', 'ho', 'admin', 'admin_ehs'):
            return Response([])
        qs = NotificaEvento.objects.exclude(letta_da=request.user).filter(
            created_at__gt=request.user.created_at
        ).order_by('created_at')
        return Response([
            {
                'id': n.id,
                'tipo': n.tipo,
                'snap_attivita_nome': n.snap_attivita_nome,
                'snap_data': str(n.snap_data),
                'snap_location': n.snap_location,
                'snap_creato_da': n.snap_creato_da,
                'snap_motivazione': n.snap_motivazione,
            }
            for n in qs
        ])

    def patch(self, request, pk):
        try:
            n = NotificaEvento.objects.get(pk=pk)
        except NotificaEvento.DoesNotExist:
            return Response({'detail': 'Non trovata.'}, status=404)
        n.letta_da.add(request.user)
        return Response({'ok': True})


class EventoDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = EventoDetailSerializer
    queryset = Evento.objects.select_related('attivita', 'host', 'location_store', 'created_by', 'ehs_sessione')

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAdminOrHOEHS()]

    def perform_update(self, serializer):
        dati = serializer.validated_data
        attivita = dati.get('attivita', serializer.instance.attivita)
        if sola_visione_ehs(self.request.user) and (
                serializer.instance.is_ehs or dati.get('is_ehs') or attivita.tipologia == 'ehs'):
            self.permission_denied(self.request, message=MESSAGGIO_SOLA_VISIONE_EHS)
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_ehs and sola_visione_ehs(request.user):
            self.permission_denied(request, message=MESSAGGIO_SOLA_VISIONE_EHS)
        motivazione = (request.data.get('motivazione') or request.query_params.get('motivazione') or '').strip()
        if not motivazione:
            return Response({'detail': 'La motivazione è obbligatoria per annullare un evento.'}, status=400)
        location = instance.location_store.nome if instance.location_store else instance.location_esterna or '—'
        notifica = NotificaEvento.objects.create(
            tipo='annullata',
            snap_attivita_nome=instance.attivita.nome,
            snap_data=instance.data,
            snap_location=location,
            snap_creato_da=f'{request.user.cognome} {request.user.nome}',
            snap_motivazione=motivazione,
        )
        notifica.letta_da.add(request.user)
        instance.delete()
        return Response(status=204)


class EccezioneCalendarioSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = EccezioneCalendario
        fields = ['id', 'data', 'nome_evento', 'created_at']
        read_only_fields = ['created_at']


class EccezioneCalendarioListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAdminOrHOOrAreaEHS()]

    def get(self, request):
        qs = EccezioneCalendario.objects.all()
        anno = request.query_params.get('anno')
        mese = request.query_params.get('mese')
        if anno and mese:
            qs = qs.filter(data__year=anno, data__month=mese)
        elif anno:
            qs = qs.filter(data__year=anno)
        return Response(EccezioneCalendarioSerializer(qs, many=True).data)

    def post(self, request):
        s = EccezioneCalendarioSerializer(data=request.data)
        if s.is_valid():
            s.save()
            return Response(s.data, status=201)
        return Response(s.errors, status=400)


class EccezioneCalendarioDetailView(APIView):
    permission_classes = [IsAdminOrHOOrAreaEHS]

    def delete(self, request, pk):
        try:
            EccezioneCalendario.objects.get(pk=pk).delete()
            return Response(status=204)
        except EccezioneCalendario.DoesNotExist:
            return Response(status=404)
