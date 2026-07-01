from datetime import date, timedelta
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.db.models import Prefetch
from django.utils import timezone
from .models import Iscrizione, RichiestaCancellazione
from .serializers import IscrizioneSerializer, RichiestaCancellazioneSerializer
from users.permissions import IsAdminOrHO, IsAdminOrHOOrArea, CanManageUsers

GIORNI_BLOCCO = 20


class IscrizioneListCreateView(generics.ListCreateAPIView):
    serializer_class = IscrizioneSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        qs = Iscrizione.objects.select_related(
            'user', 'user__store', 'user__ruolo',
            'evento', 'evento__attivita', 'evento__location_store'
        ).prefetch_related(
            Prefetch(
                'richieste_cancellazione',
                queryset=RichiestaCancellazione.objects.filter(stato='pending').only('id', 'iscrizione_id'),
                to_attr='pending_richieste',
            )
        )
        evento_id = self.request.query_params.get('evento')
        if evento_id:
            qs = qs.filter(evento_id=evento_id)
        user_id = self.request.query_params.get('user')
        if user_id:
            qs = qs.filter(user_id=user_id)
        if user.livello_accesso == 'store' and not evento_id:
            qs = qs.filter(user__store=user.store)
        data_da = self.request.query_params.get('data_da')
        data_a = self.request.query_params.get('data_a')
        if data_da:
            qs = qs.filter(evento__data__gte=data_da)
        if data_a:
            qs = qs.filter(evento__data__lte=data_a)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        target_user_id = serializer.validated_data['user'].id
        from django.contrib.auth import get_user_model
        User = get_user_model()
        target_user = User.objects.get(pk=target_user_id)
        if user.livello_accesso == 'store' and target_user.store_id != user.store_id:
            self.permission_denied(self.request, message='Puoi iscrivere solo collaboratori del tuo store.')
        serializer.save()


class IscrizioneDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = IscrizioneSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Iscrizione.objects.select_related('user', 'user__store', 'evento', 'evento__attivita')
        if user.livello_accesso == 'store':
            qs = qs.filter(user__store=user.store)
        return qs

    def destroy(self, request, *args, **kwargs):
        user = request.user
        if user.livello_accesso == 'store':
            iscrizione = self.get_object()
            delta = (iscrizione.evento.data - date.today()).days
            if delta < GIORNI_BLOCCO:
                return Response(
                    {'detail': 'Eliminazione bloccata: mancano meno di 20 giorni all\'evento. Invia una richiesta di cancellazione.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        return super().destroy(request, *args, **kwargs)


class DeleteAssentiView(APIView):
    """DELETE /iscrizioni/assenti/ — rimuove tutte le iscrizioni con stato='assente'."""
    permission_classes = [IsAdminOrHOOrArea]

    def delete(self, request):
        user = request.user
        qs = Iscrizione.objects.filter(stato='assente')
        if user.livello_accesso == 'store':
            qs = qs.filter(user__store=user.store)
        params = request.query_params
        if params.get('data_da'):
            qs = qs.filter(evento__data__gte=params['data_da'])
        if params.get('data_a'):
            qs = qs.filter(evento__data__lte=params['data_a'])
        if params.get('ruolo'):
            qs = qs.filter(user__ruolo_id=params['ruolo'])
        if params.get('store') and user.livello_accesso in ('admin', 'ho', 'area'):
            qs = qs.filter(user__store_id=params['store'])
        count, _ = qs.delete()
        return Response({'eliminati': count})


class ReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.livello_accesso == 'base':
            return Response({'detail': 'Accesso negato.'}, status=403)

        qs = Iscrizione.objects.select_related(
            'user', 'user__store', 'user__ruolo',
            'evento', 'evento__attivita', 'evento__location_store'
        ).filter(stato__in=['partecipato', 'assente', 'iscritto'])

        if user.livello_accesso == 'store':
            qs = qs.filter(user__store=user.store)

        params = request.query_params
        if params.get('data_da'):
            qs = qs.filter(evento__data__gte=params['data_da'])
        if params.get('data_a'):
            qs = qs.filter(evento__data__lte=params['data_a'])
        if params.get('ruolo'):
            qs = qs.filter(user__ruolo_id=params['ruolo'])
        if params.get('store') and user.livello_accesso in ('admin', 'ho', 'area'):
            qs = qs.filter(user__store_id=params['store'])

        serializer = IscrizioneSerializer(qs.order_by('-evento__data'), many=True)
        return Response(serializer.data)


class RichiestaCancellazioneListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Q
        user = request.user
        qs = RichiestaCancellazione.objects.select_related(
            'richiedente', 'richiedente__store',
            'processed_by',
            'iscrizione', 'iscrizione__user', 'iscrizione__user__store',
            'iscrizione__evento', 'iscrizione__evento__attivita',
        )
        if user.livello_accesso == 'store':
            qs = qs.filter(richiedente__store=user.store)
        elif user.livello_accesso == 'admin':
            pass  # vede tutto
        elif user.livello_accesso == 'ho':
            ruolo_nome = user.ruolo.nome if user.ruolo else ''
            if ruolo_nome == 'L&D':
                qs = qs.filter(snap_tipologia='ld')
            elif ruolo_nome == 'Recruiting':
                qs = qs.filter(snap_tipologia='recruiting')
            # HO senza ruolo specifico vede tutto
        else:
            return Response([], status=200)
        stato = request.query_params.get('stato')
        if stato:
            qs = qs.filter(stato=stato)
        return Response(RichiestaCancellazioneSerializer(qs, many=True).data)

    def post(self, request):
        user = request.user
        if user.livello_accesso not in ('store', 'admin', 'ho'):
            return Response({'detail': 'Non autorizzato.'}, status=403)

        iscrizione_id = request.data.get('iscrizione')
        motivazione = request.data.get('motivazione', '').strip()
        if not iscrizione_id or not motivazione:
            return Response({'detail': 'Iscrizione e motivazione obbligatorie.'}, status=400)

        try:
            iscrizione = Iscrizione.objects.select_related(
                'user', 'user__store', 'evento', 'evento__attivita'
            ).get(pk=iscrizione_id)
        except Iscrizione.DoesNotExist:
            return Response({'detail': 'Iscrizione non trovata.'}, status=404)

        if user.livello_accesso == 'store' and iscrizione.user.store_id != user.store_id:
            return Response({'detail': 'Iscrizione non di questo store.'}, status=403)

        delta = (iscrizione.evento.data - date.today()).days
        if delta >= GIORNI_BLOCCO:
            return Response({'detail': 'Puoi eliminare direttamente (più di 20 giorni all\'evento).'}, status=400)

        richiesta = RichiestaCancellazione.objects.create(
            iscrizione=iscrizione,
            richiedente=user,
            motivazione=motivazione,
            snap_attivita_nome=iscrizione.evento.attivita.nome,
            snap_evento_data=iscrizione.evento.data,
            snap_partecipante_nome=f'{iscrizione.user.cognome} {iscrizione.user.nome}',
            snap_store_nome=iscrizione.user.store.nome if iscrizione.user.store else '',
            snap_tipologia=iscrizione.evento.attivita.tipologia,
        )
        return Response(RichiestaCancellazioneSerializer(richiesta).data, status=201)


class RichiestaCancellazioneDetailView(APIView):
    permission_classes = [IsAdminOrHO]

    def patch(self, request, pk):
        try:
            richiesta = RichiestaCancellazione.objects.select_related(
                'iscrizione', 'iscrizione__user', 'iscrizione__user__store',
                'iscrizione__evento', 'iscrizione__evento__attivita',
            ).get(pk=pk)
        except RichiestaCancellazione.DoesNotExist:
            return Response(status=404)

        nuovo_stato = request.data.get('stato')
        if nuovo_stato not in ('approvata', 'rifiutata'):
            return Response({'detail': 'Stato non valido.'}, status=400)

        if richiesta.stato != 'pending':
            return Response({'detail': 'Richiesta già processata.'}, status=400)

        if nuovo_stato == 'approvata' and richiesta.iscrizione:
            richiesta.iscrizione.delete()
            richiesta.iscrizione = None  # allinea oggetto in-memory al SET_NULL del DB

        richiesta.stato = nuovo_stato
        richiesta.processed_by = request.user
        richiesta.processed_at = timezone.now()
        richiesta.notifica_letta = False
        richiesta.save()

        return Response(RichiestaCancellazioneSerializer(richiesta).data)


class NotificheView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.livello_accesso not in ('store',):
            return Response([])
        qs = RichiestaCancellazione.objects.filter(
            richiedente__store=user.store,
            stato__in=('approvata', 'rifiutata'),
            notifica_letta=False,
        )
        return Response(RichiestaCancellazioneSerializer(qs, many=True).data)

    def post(self, request):
        user = request.user
        if user.livello_accesso == 'store':
            RichiestaCancellazione.objects.filter(
                richiedente__store=user.store,
                notifica_letta=False,
            ).update(notifica_letta=True)
        return Response({'ok': True})
