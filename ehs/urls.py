from django.urls import path

from . import views

urlpatterns = [
    path('ehs/corsi/', views.EHSCorsoListView.as_view(), name='ehs-corso-list'),
    path('ehs/sessioni/', views.EHSSessioneListCreateView.as_view(), name='ehs-sessione-list'),
    path('ehs/sessioni/<int:pk>/', views.EHSSessioneDetailView.as_view(), name='ehs-sessione-detail'),
    path('ehs/sessioni/<int:pk>/proponi-data/', views.EHSProponiDataView.as_view(), name='ehs-proponi-data'),
    path('ehs/sessioni/<int:pk>/rispondi-data/', views.EHSRispondiDataView.as_view(), name='ehs-rispondi-data'),
    path('ehs/sessioni/<int:pk>/conferma/', views.EHSConfermaView.as_view(), name='ehs-conferma'),
    path('ehs/sessioni/<int:pk>/registro/', views.EHSRegistroView.as_view(), name='ehs-registro'),
    path('ehs/sessioni/<int:pk>/registro-compilato/', views.EHSRegistroCompilatoView.as_view(), name='ehs-registro-compilato'),
    path('ehs/sessioni/<int:pk>/chiudi-aula/', views.EHSChiudiAulaView.as_view(), name='ehs-chiudi-aula'),
    path('ehs/sessioni/<int:pk>/annulla/', views.EHSAnnullaView.as_view(), name='ehs-annulla'),
    path('ehs/calendario/', views.EHSCalendarioView.as_view(), name='ehs-calendario'),
    path('ehs/notifiche-scadenza/', views.EHSNotificaScadenzaView.as_view(), name='ehs-notifiche-scadenza'),
    path('ehs/notifiche-scadenza/<int:pk>/', views.EHSNotificaScadenzaView.as_view(), name='ehs-notifica-scadenza-detail'),
]
