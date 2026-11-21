from django.urls import path

from .views import (
    CookieLogoutView,
    CookieRefreshView,
    CookieTokenObtainPairView,
    PasswordResetConfirmView,
    PasswordResetView,
    RegistrationView,
    VerifyOTPView,
)

urlpatterns = [
    path('register/', RegistrationView.as_view(), name='registration'),
    path('activate/<uidb64>/<token>/', VerifyOTPView.as_view(), name='activate'),
    path('login/', CookieTokenObtainPairView.as_view(), name='login'),
    path('logout/', CookieLogoutView.as_view(), name='logout'),
    path('token/refresh/', CookieRefreshView.as_view(), name='refresh'),
    path('password_reset/', PasswordResetView.as_view(), name='password_reset'),
    path('password_confirm/<uidb64>/<token>/', PasswordResetConfirmView.as_view(), name='password_confirm'),
]