from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.permissions import IsAdmin

from .models import RichiestaAssistenza
from .serializers import GestioneRichiestaSerializer, RichiestaAssistenzaSerializer


class RichiesteAssistenzaView(APIView):
    """GET: l'Admin vede tutte le richieste (?stato, ?tipo), gli altri solo le proprie.
    POST: chiunque invia un suggerimento, un'idea o una richiesta di aiuto."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = RichiestaAssistenza.objects.select_related('utente', 'utente__store', 'risposto_da')
        if request.user.livello_accesso == 'admin':
            for campo in ('stato', 'tipo'):
                if request.query_params.get(campo):
                    qs = qs.filter(**{campo: request.query_params[campo]})
        else:
            qs = qs.filter(utente=request.user)
        return Response(RichiestaAssistenzaSerializer(qs, many=True).data)

    def post(self, request):
        if request.user.sola_lettura:
            return Response({'detail': 'Profilo in sola lettura: operazione non consentita.'}, status=403)
        serializer = RichiestaAssistenzaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        richiesta = serializer.save(utente=request.user)
        return Response(RichiestaAssistenzaSerializer(richiesta).data, status=201)


class RichiestaAssistenzaDetailView(APIView):
    """PATCH {risposta?, stato?} — solo l'Admin."""
    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        richiesta = get_object_or_404(RichiestaAssistenza, pk=pk)
        serializer = GestioneRichiestaSerializer(richiesta, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        nuova_risposta = 'risposta' in serializer.validated_data and \
            serializer.validated_data['risposta'].strip() != richiesta.risposta.strip()
        richiesta = serializer.save()
        if nuova_risposta:
            richiesta.risposta_il = timezone.now()
            richiesta.risposto_da = request.user
            richiesta.risposta_letta = not richiesta.risposta.strip()
            richiesta.save(update_fields=['risposta_il', 'risposto_da', 'risposta_letta'])
        return Response(RichiestaAssistenzaSerializer(richiesta).data)


class ContatoriAssistenzaView(APIView):
    """GET — numero per il pallino nel menu: richieste nuove (Admin) o risposte non lette (altri).
    POST — l'utente ha aperto l'Assistenza: le risposte risultano lette."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.livello_accesso == 'admin':
            return Response({'da_vedere': RichiestaAssistenza.objects.filter(stato='nuova').count()})
        return Response({'da_vedere': RichiestaAssistenza.objects.filter(utente=request.user, risposta_letta=False).count()})

    def post(self, request):
        RichiestaAssistenza.objects.filter(utente=request.user, risposta_letta=False).update(risposta_letta=True)
        return Response({'ok': True})
