from django.urls import path
from .views import (
    HostListCreateView, HostDetailView,
    AttivitaCatalogoListCreateView, AttivitaCatalogoDetailView,
    EventoListCreateView, EventoDetailView,
    EccezioneCalendarioListCreateView, EccezioneCalendarioDetailView,
    NotificaEventoView,
    RichiediDisattivazioneAttivitaView, RichiesteDisattivazioneAttivitaView, RichiestaDisattivazioneAttivitaDetailView,
)

urlpatterns = [
    path('host/', HostListCreateView.as_view(), name='host-list'),
    path('host/<int:pk>/', HostDetailView.as_view(), name='host-detail'),
    path('attivita/', AttivitaCatalogoListCreateView.as_view(), name='attivita-list'),
    path('attivita/<int:pk>/', AttivitaCatalogoDetailView.as_view(), name='attivita-detail'),
    path('attivita/<int:pk>/richiedi-disattivazione/', RichiediDisattivazioneAttivitaView.as_view(), name='attivita-richiedi-disattivazione'),
    path('richieste-disattivazione-attivita/', RichiesteDisattivazioneAttivitaView.as_view(), name='richieste-disattivazione-attivita'),
    path('richieste-disattivazione-attivita/<int:pk>/', RichiestaDisattivazioneAttivitaDetailView.as_view(), name='richiesta-disattivazione-attivita'),
    path('eventi/', EventoListCreateView.as_view(), name='evento-list'),
    path('eventi/<int:pk>/', EventoDetailView.as_view(), name='evento-detail'),
    path('eccezioni/', EccezioneCalendarioListCreateView.as_view(), name='eccezione-list'),
    path('eccezioni/<int:pk>/', EccezioneCalendarioDetailView.as_view(), name='eccezione-detail'),
    path('notifiche-evento/', NotificaEventoView.as_view(), name='notifiche-evento'),
    path('notifiche-evento/<int:pk>/', NotificaEventoView.as_view(), name='notifica-evento-detail'),
]
