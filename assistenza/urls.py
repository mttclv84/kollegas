from django.urls import path

from .views import ContatoriAssistenzaView, RichiestaAssistenzaDetailView, RichiesteAssistenzaView

urlpatterns = [
    path('assistenza/', RichiesteAssistenzaView.as_view(), name='assistenza-list'),
    path('assistenza/contatori/', ContatoriAssistenzaView.as_view(), name='assistenza-contatori'),
    path('assistenza/<int:pk>/', RichiestaAssistenzaDetailView.as_view(), name='assistenza-detail'),
]
