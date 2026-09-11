from django.urls import path

from . import views

urlpatterns = [
    path('ehs/corsi/', views.EHSCorsoListView.as_view(), name='ehs-corso-list'),
    path('ehs/sessioni/', views.EHSSessioneListCreateView.as_view(), name='ehs-sessione-list'),
    path('ehs/sessioni/<int:pk>/', views.EHSSessioneDetailView.as_view(), name='ehs-sessione-detail'),
    path('ehs/sessioni/<int:pk>/proponi-data/', views.EHSProponiDataView.as_view(), name='ehs-proponi-data'),
    path('ehs/sessioni/<int:pk>/rispondi-data/', views.EHSRispondiDataView.as_view(), name='ehs-rispondi-data'),
    path('ehs/sessioni/<int:pk>/accetta-controproposta/', views.EHSAccettaContropropostaView.as_view(), name='ehs-accetta-controproposta'),
    path('ehs/sessioni/<int:pk>/chiudi-aula/', views.EHSChiudiAulaView.as_view(), name='ehs-chiudi-aula'),
    path('ehs/sessioni/<int:pk>/annulla/', views.EHSAnnullaView.as_view(), name='ehs-annulla'),
    path('ehs/calendario/', views.EHSCalendarioView.as_view(), name='ehs-calendario'),
    path('ehs/notifiche-scadenza/', views.EHSNotificaScadenzaView.as_view(), name='ehs-notifiche-scadenza'),
    path('ehs/notifiche-scadenza/<int:pk>/', views.EHSNotificaScadenzaView.as_view(), name='ehs-notifica-scadenza-detail'),
    path('ehs/notifiche-conferma/', views.EHSNotificaSessioneConfermataView.as_view(), name='ehs-notifiche-conferma'),
    path('ehs/notifiche-conferma/<int:pk>/', views.EHSNotificaSessioneConfermataView.as_view(), name='ehs-notifica-conferma-detail'),
    path('ehs/fornitori/', views.EHSFornitoreListCreateView.as_view(), name='ehs-fornitore-list'),
    path('ehs/fornitori/<int:pk>/', views.EHSFornitoreDetailView.as_view(), name='ehs-fornitore-detail'),
    path('ehs/registri/', views.EHSRegistriView.as_view(), name='ehs-registri'),
    path('ehs/registri/<int:pk>/file/', views.EHSRegistroFileView.as_view(), name='ehs-registro-file'),
]
