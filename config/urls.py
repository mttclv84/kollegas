from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView
from users.views import CambiaPasswordView, CustomTokenObtainPairView, LogoutView, RichiediResetPasswordView
from archivio.views import servi_media

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),
    path('api/auth/cambia-password/', CambiaPasswordView.as_view(), name='cambia-password'),
    path('api/auth/richiedi-reset/', RichiediResetPasswordView.as_view(), name='richiedi-reset'),
    path('api/', include('users.urls')),
    path('api/', include('stores.urls')),
    path('api/', include('events.urls')),
    path('api/', include('participants.urls')),
    path('api/', include('ehs.urls')),
    path('api/', include('guida.urls')),
    # File caricati (archiviati nel database): pubblici solo i percorsi ammessi, es. foto.
    path('media/<path:nome>', servi_media, name='media'),
]
