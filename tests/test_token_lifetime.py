from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from auth_app.models import CustomUser


class TokenLifetimeTest(TestCase):
    """Verify token lifetimes through the authentication endpoints."""

    def test_login_and_refresh_issue_30_minute_access_tokens(self):
        """Login and refresh return access cookies and tokens valid for 30 minutes."""
        CustomUser.objects.create_user(
            username='viewer@example.com', email='viewer@example.com',
            password='strong-test-password', is_verified=True,
        )
        client = APIClient()
        login = client.post('/api/login/', {
            'email': 'viewer@example.com', 'password': 'strong-test-password',
        }, format='json')
        self.assertEqual(login.status_code, 200)
        self.assert_access_lifetime(login)
        refresh = client.post('/api/token/refresh/', {}, format='json')
        self.assertEqual(refresh.status_code, 200)
        self.assert_access_lifetime(refresh)

    def assert_access_lifetime(self, response):
        """Check the response's cookie and JWT lifetime against 30 minutes."""
        cookie = response.cookies['access_token']
        token = AccessToken(cookie.value)
        self.assertEqual(int(cookie['max-age']), 1800)
        self.assertEqual(token['exp'] - token['iat'], 1800)