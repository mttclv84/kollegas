from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers as drf_serializers
from .models import Host, AttivitaCatalogo, Evento, EccezioneCalendario, NotificaEvento
from .serializers import HostSerializer, AttivitaCatalogoSerializer, EventoListSerializer, EventoDetailSerializer
from users.permissions import IsAdminOrHO, IsAdminOrHOOrArea


class HostListCreateView(generics.ListCreateAPIView):
    serializer_class = HostSerializer
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
    serializer_class = AttivitaCatalogoSerializer
    queryset = AttivitaCatalogo.objects.filter(is_active=True).prefetch_related('ruoli_destinatari')

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAdminOrHOOrArea()]


class AttivitaCatalogoDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AttivitaCatalogoSerializer
    queryset = AttivitaCatalogo.objects.all()

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAdminOrHOOrArea()]


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
        qs = Evento.objects.select_related('attivita', 'host', 'location_store').prefetch_related('iscrizioni')
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
            return [IsAdminOrHOOrArea()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        super().perform_create(serializer)
        actor = self.request.user
        if actor.livello_accesso in ('admin', 'ho'):
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
        if request.user.livello_accesso not in ('store', 'ho', 'admin'):
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
    queryset = Evento.objects.select_related('attivita', 'host', 'location_store', 'created_by')

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAdminOrHOOrArea()]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
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
        return [IsAdminOrHOOrArea()]

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
    permission_classes = [IsAdminOrHOOrArea]

    def delete(self, request, pk):
        try:
            EccezioneCalendario.objects.get(pk=pk).delete()
            return Response(status=204)
        except EccezioneCalendario.DoesNotExist:
            return Response(status=404)
