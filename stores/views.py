from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from .models import Store, StoreCluster, Area
from .serializers import StoreSerializer, StoreListSerializer, StoreClusterSerializer, AreaSerializer
from users.permissions import IsAdmin, IsAdminOrHO, IsAdminOrHOEHS, IsAdminOrHOOrAreaEHS


def _sync_store_user(store, password=None):
    """Crea o aggiorna il profilo User collegato allo store per l'accesso al portale."""
    from users.models import User
    try:
        user = User.objects.get(livello_accesso='store', store=store)
    except User.DoesNotExist:
        user = User(livello_accesso='store', store=store)

    user.email = store.email_store
    user.cognome = store.nome
    user.nome = ''
    user.is_active = store.is_active

    # La password salvata sul negozio vale solo per creare l'account: riscriverla a ogni
    # modifica del negozio annullerebbe quella scelta dall'utente.
    pwd = password or (store.portale_password if user._state.adding else None)
    if pwd:
        user.imposta_password_temporanea(pwd)

    user.save()

class StoreListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return StoreSerializer
        return StoreListSerializer

    def get_queryset(self):
        return Store.objects.filter(is_active=True).prefetch_related('collaboratori')

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAdmin()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        store = serializer.save()
        _sync_store_user(store, password=store.portale_password)


class StoreDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = StoreSerializer

    def get_queryset(self):
        return Store.objects.all()

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAdmin()]

    def perform_update(self, serializer):
        store = serializer.save()
        password = self.request.data.get('portale_password')
        _sync_store_user(store, password=password)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_active = False
        instance.save()
        _sync_store_user(instance)  # disattiva anche il User collegato
        return Response(status=status.HTTP_204_NO_CONTENT)


class StoreClusterView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, store_id):
        cluster, _ = StoreCluster.objects.get_or_create(store_id=store_id)
        return Response(StoreClusterSerializer(cluster).data)

    def put(self, request, store_id):
        cluster, _ = StoreCluster.objects.get_or_create(store_id=store_id)
        serializer = StoreClusterSerializer(cluster, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MappingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        from users.models import User, Role
        from django.db.models import Count

        try:
            store = Store.objects.get(pk=store_id, is_active=True)
        except Store.DoesNotExist:
            return Response({'detail': 'Store non trovato.'}, status=404)

        cluster, _ = StoreCluster.objects.get_or_create(store=store)

        users = User.objects.filter(
            store=store, is_active=True
        ).select_related('ruolo').order_by('ruolo__nome', 'cognome')

        from users.serializers import UserListSerializer
        users_data = UserListSerializer(users, many=True).data

        cluster_data = StoreClusterSerializer(cluster).data

        area = store.aree.first()
        area_info = None
        if area:
            area_info = {
                'numero': area.numero,
                'area_manager_retail': area.area_manager_retail,
                'area_bp': area.area_bp,
            }

        return Response({
            'store': {'id': store.id, 'nome': store.nome},
            'cluster': cluster_data,
            'collaboratori': users_data,
            'area': area_info,
        })


class AreaListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        areas = Area.objects.prefetch_related('stores').all()
        return Response(AreaSerializer(areas, many=True).data)


class AreaDetailView(APIView):
    permission_classes = [IsAdmin]

    def put(self, request, pk):
        try:
            area = Area.objects.prefetch_related('stores').get(pk=pk)
        except Area.DoesNotExist:
            return Response(status=404)
        serializer = AreaSerializer(area, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
