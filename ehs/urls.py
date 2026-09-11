from django.urls import path

from . import views

urlpatterns = [
    path('ehs/corsi/', views.EHSCorsoListCreateView.as_view(), name='ehs-corso-list'),
    path('ehs/corsi/<int:pk>/', views.EHSCorsoDetailView.as_view(), name='ehs-corso-detail'),
    path('ehs/verifica-partecipante/', views.EHSVerificaPartecipanteView.as_view(), name='ehs-verifica-partecipante'),
    path('ehs/sessioni/', views.EHSSessioneListCreateView.as_view(), name='ehs-sessione-list'),
    path('ehs/sessioni/<int:pk>/', views.EHSSessioneDetailView.as_view(), name='ehs-sessione-detail'),
    path('ehs/sessioni/<int:pk>/proponi-data/', views.EHSProponiDataView.as_view(), name='ehs-proponi-data'),
    path('ehs/sessioni/<int:pk>/rispondi-data/', views.EHSRispondiDataView.as_view(), name='ehs-rispondi-data'),
    path('ehs/sessioni/<int:pk>/accetta-controproposta/', views.EHSAccettaContropropostaView.as_view(), name='ehs-accetta-controproposta'),
    path('ehs/sessioni/<int:pk>/chiudi-aula/', views.EHSChiudiAulaView.as_view(), name='ehs-chiudi-aula'),
    path('ehs/sessioni/<int:pk>/annulla/', views.EHSAnnullaView.as_view(), name='ehs-annulla'),
    path('ehs/sessioni/<int:pk>/assegna-fornitore/', views.EHSAssegnaFornitoreView.as_view(), name='ehs-assegna-fornitore'),
    path('ehs/calendario/', views.EHSCalendarioView.as_view(), name='ehs-calendario'),
    path('ehs/notifiche-scadenza/', views.EHSNotificaScadenzaView.as_view(), name='ehs-notifiche-scadenza'),
    path('ehs/notifiche-scadenza/<int:pk>/', views.EHSNotificaScadenzaView.as_view(), name='ehs-notifica-scadenza-detail'),
    path('ehs/notifiche-conferma/', views.EHSNotificaSessioneConfermataView.as_view(), name='ehs-notifiche-conferma'),
    path('ehs/notifiche-conferma/<int:pk>/', views.EHSNotificaSessioneConfermataView.as_view(), name='ehs-notifica-conferma-detail'),
    path('ehs/notifiche-conferma-store/', views.EHSNotificaSessioneConfermataStoreView.as_view(), name='ehs-notifiche-conferma-store'),
    path('ehs/notifiche-conferma-store/<int:pk>/', views.EHSNotificaSessioneConfermataStoreView.as_view(), name='ehs-notifica-conferma-store-detail'),
    path('ehs/notifiche-data-proposta/', views.EHSNotificaDataPropostaView.as_view(), name='ehs-notifiche-data-proposta'),
    path('ehs/notifiche-data-proposta/<int:pk>/', views.EHSNotificaDataPropostaView.as_view(), name='ehs-notifica-data-proposta-detail'),
    path('ehs/notifiche-richiesta/', views.EHSNotificaNuovaRichiestaView.as_view(), name='ehs-notifiche-richiesta'),
    path('ehs/notifiche-richiesta/<int:pk>/', views.EHSNotificaNuovaRichiestaView.as_view(), name='ehs-notifica-richiesta-detail'),
    path('ehs/fornitori/', views.EHSFornitoreListCreateView.as_view(), name='ehs-fornitore-list'),
    path('ehs/fornitori/<int:pk>/', views.EHSFornitoreDetailView.as_view(), name='ehs-fornitore-detail'),
    path('ehs/registri/', views.EHSRegistriView.as_view(), name='ehs-registri'),
    path('ehs/registri/<int:pk>/', views.EHSRegistroDeleteView.as_view(), name='ehs-registro-delete'),
    path('ehs/registri/<int:pk>/file/', views.EHSRegistroFileView.as_view(), name='ehs-registro-file'),
]
