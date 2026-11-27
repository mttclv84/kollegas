from rest_framework import generics
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from users.permissions import IsAdmin

from .models import ArgomentoGuida
from .serializers import ArgomentoGuidaSerializer


class _PermessiGuida:
    """Leggono tutti (solo gli argomenti attivi del proprio profilo); scrive solo l'Admin."""
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    serializer_class = ArgomentoGuidaSerializer
    pagination_class = None

    def get_permissions(self):
        return [IsAuthenticated()] if self.request.method == 'GET' else [IsAdmin()]

    def get_queryset(self):
        user = self.request.user
        qs = ArgomentoGuida.objects.select_related('aggiornato_da')
        if user.livello_accesso == 'admin':
            profilo = self.request.query_params.get('profilo')
            return qs.filter(profilo=profilo) if profilo else qs
        return qs.filter(profilo=user.livello_accesso, attivo=True)


class ArgomentiGuidaView(_PermessiGuida, generics.ListCreateAPIView):
    pass


class ArgomentoGuidaDetailView(_PermessiGuida, generics.RetrieveUpdateDestroyAPIView):
    def perform_destroy(self, instance):
        if instance.immagine:
            instance.immagine.delete(save=False)
        instance.delete()
