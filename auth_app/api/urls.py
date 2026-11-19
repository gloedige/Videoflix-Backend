# Third-party
from django.urls import path

# Local imports
from .views import RegistrationView, CookieRefreshView, CookieTokenObtainPairView, CookieLogoutView, VerifyOTPView

urlpatterns = [
    path('register/', RegistrationView.as_view(), name='registration'),
    path('activate/<uidb64>/<token>/', VerifyOTPView.as_view(), name='activate'),
    path('login/', CookieTokenObtainPairView.as_view(), name='login'),
    path('logout/', CookieLogoutView.as_view(), name='logout'),
    path('token/refresh/', CookieRefreshView.as_view(), name='refresh'),
]