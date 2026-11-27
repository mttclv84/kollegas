from django.urls import path

from .views import ArgomentiGuidaView, ArgomentoGuidaDetailView

urlpatterns = [
    path('guida/', ArgomentiGuidaView.as_view(), name='guida-list'),
    path('guida/<int:pk>/', ArgomentoGuidaDetailView.as_view(), name='guida-detail'),
]
