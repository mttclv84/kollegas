from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from .models import Store, StoreCluster, Area
from .serializers import StoreSerializer, StoreListSerializer, StoreClusterSerializer, AreaSerializer
from users.permissions import IsAdmin, IsAdminOrHO


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

    pwd = password or store.portale_password
    if pwd:
        user.set_password(pwd)
        user.raw_password = pwd

    user.save()

GWU_CORSI_OBBLIGATORI = [
    'GWU RA-TM / Management di Base | OBBLIGATORIO',
    'GWU RA-TM / Valutazione e Feedback | OBBLIGATORIO',
    'GWU RA-TM / Report&Sistemi | OBBLIGATORIO',
]


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


class CompletamentoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        from users.models import User
        from events.models import AttivitaCatalogo
        from participants.models import Iscrizione

        try:
            store = Store.objects.get(pk=store_id, is_active=True)
        except Store.DoesNotExist:
            return Response({'detail': 'Store non trovato.'}, status=404)

        target_roles = ['GWU RA-TM', 'Team Manager']
        users = list(User.objects.filter(
            store=store, is_active=True, ruolo__nome__in=target_roles
        ).select_related('ruolo'))

        gwu_ids = {u.id for u in users if u.ruolo and u.ruolo.nome == 'GWU RA-TM'}
        tm_ids = {u.id for u in users if u.ruolo and u.ruolo.nome == 'Team Manager'}
        all_ids = gwu_ids | tm_ids

        result = []
        for nome_corso in GWU_CORSI_OBBLIGATORI:
            try:
                attivita = AttivitaCatalogo.objects.get(nome=nome_corso)
            except AttivitaCatalogo.DoesNotExist:
                continue

            partecipanti = set(Iscrizione.objects.filter(
                evento__attivita=attivita,
                stato='partecipato',
                user_id__in=all_ids,
            ).values_list('user_id', flat=True))

            iscritti_ids = set(Iscrizione.objects.filter(
                evento__attivita=attivita,
                stato='iscritto',
                user_id__in=all_ids,
            ).values_list('user_id', flat=True))

            in_procinto = iscritti_ids - partecipanti

            gwu_ok = len(partecipanti & gwu_ids)
            tm_ok = len(partecipanti & tm_ids)
            gwu_ip = len(in_procinto & gwu_ids)
            tm_ip = len(in_procinto & tm_ids)
            tot_ok = len(partecipanti)
            tot = len(all_ids)

            nome_breve = nome_corso.split('/')[1].split('|')[0].strip() if '/' in nome_corso else nome_corso

            result.append({
                'nome': nome_corso,
                'nome_breve': nome_breve,
                'percentuale': round(100 * tot_ok / tot) if tot > 0 else 0,
                'completato': tot_ok,
                'in_procinto': len(in_procinto),
                'totale': tot,
                'gwu_ratm': {'completato': gwu_ok, 'totale': len(gwu_ids), 'in_procinto': gwu_ip},
                'team_manager': {'completato': tm_ok, 'totale': len(tm_ids), 'in_procinto': tm_ip},
            })

        return Response({'store': {'id': store.id, 'nome': store.nome}, 'corsi': result})


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


class CompletamentoItaliaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from users.models import User
        from events.models import AttivitaCatalogo
        from participants.models import Iscrizione

        target_roles = ['GWU RA-TM', 'Team Manager']
        all_users = list(User.objects.filter(
            is_active=True, ruolo__nome__in=target_roles
        ).select_related('ruolo', 'store'))
        all_user_ids = {u.id for u in all_users}

        areas = list(Area.objects.prefetch_related('stores').all())
        area_store_sets = {a.numero: set(a.stores.values_list('id', flat=True)) for a in areas}

        corso_data = []
        for nome_corso in GWU_CORSI_OBBLIGATORI:
            try:
                attivita = AttivitaCatalogo.objects.get(nome=nome_corso)
            except AttivitaCatalogo.DoesNotExist:
                continue
            partecipanti = set(Iscrizione.objects.filter(
                evento__attivita=attivita, stato='partecipato', user_id__in=all_user_ids,
            ).values_list('user_id', flat=True))
            nome_breve = nome_corso.split('/')[1].split('|')[0].strip() if '/' in nome_corso else nome_corso
            corso_data.append({'nome_corso': nome_corso, 'nome_breve': nome_breve, 'partecipanti': partecipanti})

        def build_stats(user_subset):
            gwu_ids = {u.id for u in user_subset if u.ruolo and u.ruolo.nome == 'GWU RA-TM'}
            tm_ids  = {u.id for u in user_subset if u.ruolo and u.ruolo.nome == 'Team Manager'}
            uid = gwu_ids | tm_ids
            tot = len(uid)
            return [
                {
                    'nome_breve': c['nome_breve'],
                    'percentuale': round(100 * len(c['partecipanti'] & uid) / tot) if tot else 0,
                    'completato': len(c['partecipanti'] & uid),
                    'totale': tot,
                    'gwu_ratm':    {'completato': len(c['partecipanti'] & gwu_ids), 'totale': len(gwu_ids)},
                    'team_manager':{'completato': len(c['partecipanti'] & tm_ids),  'totale': len(tm_ids)},
                }
                for c in corso_data
            ]

        aree_data = []
        for area in areas:
            area_users = [u for u in all_users if u.store_id in area_store_sets[area.numero]]
            aree_data.append({
                'numero': area.numero,
                'area_manager_retail': area.area_manager_retail,
                'area_bp': area.area_bp,
                'corsi': build_stats(area_users),
            })

        return Response({'italia': build_stats(all_users), 'aree': aree_data})


class CompletamentoAreaDetailView(APIView):
    permission_classes = [IsAdminOrHO]

    def get(self, request, numero):
        from users.models import User
        from events.models import AttivitaCatalogo
        from participants.models import Iscrizione

        try:
            area = Area.objects.prefetch_related('stores').get(numero=numero)
        except Area.DoesNotExist:
            return Response(status=404)

        target_roles = ['GWU RA-TM', 'Team Manager']
        stores_in_area = list(area.stores.filter(is_active=True))

        # Pre-fetch participations for all GWU courses
        corso_data = []
        all_store_user_ids = set()
        store_users = {}  # store_id → list of users

        for store in stores_in_area:
            users = list(User.objects.filter(
                store=store, is_active=True, ruolo__nome__in=target_roles
            ).select_related('ruolo'))
            store_users[store.id] = users
            all_store_user_ids |= {u.id for u in users}

        for nome_corso in GWU_CORSI_OBBLIGATORI:
            try:
                attivita = AttivitaCatalogo.objects.get(nome=nome_corso)
            except AttivitaCatalogo.DoesNotExist:
                continue
            partecipanti = set(Iscrizione.objects.filter(
                evento__attivita=attivita, stato='partecipato', user_id__in=all_store_user_ids,
            ).values_list('user_id', flat=True))
            nome_breve = nome_corso.split('/')[1].split('|')[0].strip() if '/' in nome_corso else nome_corso
            corso_data.append({'nome_breve': nome_breve, 'partecipanti': partecipanti})

        stores_result = []
        for store in stores_in_area:
            users = store_users[store.id]
            gwu_ids = {u.id for u in users if u.ruolo and u.ruolo.nome == 'GWU RA-TM'}
            tm_ids  = {u.id for u in users if u.ruolo and u.ruolo.nome == 'Team Manager'}
            corsi = []
            total_untrained = 0
            for c in corso_data:
                gwu_ok = len(c['partecipanti'] & gwu_ids)
                tm_ok  = len(c['partecipanti'] & tm_ids)
                total_untrained += (len(gwu_ids) - gwu_ok) + (len(tm_ids) - tm_ok)
                corsi.append({
                    'nome_breve': c['nome_breve'],
                    'gwu_ratm':    {'completato': gwu_ok, 'totale': len(gwu_ids)},
                    'team_manager':{'completato': tm_ok,  'totale': len(tm_ids)},
                })
            stores_result.append({
                'id': store.id,
                'nome': store.nome,
                'codice_store': store.codice_store,
                'corsi': corsi,
                'total_untrained': total_untrained,
            })

        # Flag the store with the highest untrained count as alert
        if stores_result:
            max_untrained = max(s['total_untrained'] for s in stores_result)
            for s in stores_result:
                s['alert'] = (s['total_untrained'] == max_untrained and max_untrained > 0)

        return Response({
            'numero': area.numero,
            'area_manager_retail': area.area_manager_retail,
            'area_bp': area.area_bp,
            'stores': stores_result,
        })
