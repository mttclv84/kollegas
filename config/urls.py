from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenRefreshView
from users.views import CustomTokenObtainPairView, LogoutView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),
    path('api/', include('users.urls')),
    path('api/', include('stores.urls')),
    path('api/', include('events.urls')),
    path('api/', include('participants.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
