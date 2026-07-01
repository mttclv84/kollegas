from django.urls import path
from .views import StoreListCreateView, StoreDetailView, StoreClusterView, MappingView, CompletamentoView, AreaListView, AreaDetailView, CompletamentoItaliaView, CompletamentoAreaDetailView

urlpatterns = [
    path('stores/', StoreListCreateView.as_view(), name='store-list'),
    path('stores/<int:pk>/', StoreDetailView.as_view(), name='store-detail'),
    path('stores/<int:store_id>/cluster/', StoreClusterView.as_view(), name='store-cluster'),
    path('stores/<int:store_id>/mapping/', MappingView.as_view(), name='mapping'),
    path('stores/<int:store_id>/completamento/', CompletamentoView.as_view(), name='completamento'),
    path('aree/', AreaListView.as_view(), name='area-list'),
    path('aree/<int:pk>/', AreaDetailView.as_view(), name='area-detail'),
    path('completamento/italia/', CompletamentoItaliaView.as_view(), name='completamento-italia'),
    path('completamento/area/<int:numero>/', CompletamentoAreaDetailView.as_view(), name='completamento-area'),
]
