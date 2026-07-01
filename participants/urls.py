from django.urls import path
from .views import (
    IscrizioneListCreateView, IscrizioneDetailView, ReportView, DeleteAssentiView,
    RichiestaCancellazioneListCreateView, RichiestaCancellazioneDetailView, NotificheView,
)

urlpatterns = [
    path('iscrizioni/', IscrizioneListCreateView.as_view(), name='iscrizione-list'),
    path('iscrizioni/<int:pk>/', IscrizioneDetailView.as_view(), name='iscrizione-detail'),
    path('iscrizioni/assenti/', DeleteAssentiView.as_view(), name='delete-assenti'),
    path('report/', ReportView.as_view(), name='report'),
    path('richieste-cancellazione/', RichiestaCancellazioneListCreateView.as_view(), name='richieste-list'),
    path('richieste-cancellazione/<int:pk>/', RichiestaCancellazioneDetailView.as_view(), name='richieste-detail'),
    path('richieste-cancellazione/notifiche/', NotificheView.as_view(), name='richieste-notifiche'),
]
