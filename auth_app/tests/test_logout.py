from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from auth_app.models import CustomUser as User


class LogoutTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def create_user(self, email, is_verified=False, otp=None, otp_expires_at=None):
        """Create and return a user with password 'pass'."""
        return User.objects.create_user(
            username=email,
            email=email,
            password='sUp3rS3cr3t',
            is_verified=is_verified,
            otp=otp,
            otp_expires_at=otp_expires_at
        )

    def login(self, email, password):
        """POST login credentials and return the response."""
        payload = {
            'email': email,
            'password': password
        }
        return self.client.post('/api/login/', payload, format='json')
    
    def validate_cleared_token_cookies(self):
        """Assert that the response expires both JWT cookies."""
        for name in ('access_token', 'refresh_token'):
            self.assertIn(name, self.client.cookies)
            self.assertEqual(self.client.cookies[name].value, '')
            self.assertEqual(self.client.cookies[name]['max-age'], 0)

    def validate_refresh_token_on_blacklist(self, refresh_token):
        """Assert that the refresh token is blacklisted."""
        self.assertTrue(OutstandingToken.objects.filter(token=refresh_token).exists())
        self.assertTrue(BlacklistedToken.objects.filter(token__token=refresh_token).exists())

    def test_logout_without_login(self):
            """Logging out without being logged in should fail."""
            response = self.client.post('/api/logout/', format='json')
            self.assertEqual(response.status_code, 401)
    
    def test_logout_with_login(self):
        """Logging out after being logged in should succeed."""
        self.create_user('logout@example.com', is_verified=True, otp='123456')
        login_response = self.login('logout@example.com', 'sUp3rS3cr3t')
        refresh_token = login_response.cookies['refresh_token'].value
        access_token = login_response.cookies['access_token'].value

        response = self.client.post('/api/logout/', format='json')
        
        self.assertEqual(response.status_code, 200)
        self.validate_cleared_token_cookies()
        self.validate_refresh_token_on_blacklist(refresh_token)
        self.client.cookies['access_token'] = access_token
        replay_response = self.client.get('/api/video/')
        self.assertEqual(replay_response.status_code, 401)

    def test_logout_validates_access_cookie_even_with_authorization_header(self):
        """A valid bearer token must not mask a malformed access cookie at logout."""
        self.create_user('logout-header@example.com', is_verified=True, otp='123456')
        login_response = self.login('logout-header@example.com', 'sUp3rS3cr3t')
        access_token = login_response.cookies['access_token'].value
        self.client.cookies['access_token'] = 'malformed.jwt.cookie'
        response = self.client.post('/api/logout/', HTTP_AUTHORIZATION=f'Bearer {access_token}')
        self.assertEqual(response.status_code, 401)

    def test_logout_without_refresh_token(self):
        """Logging out without a refresh token should fail."""
        self.create_user('logout-no-refresh@example.com', is_verified=True, otp='123456')
        login_response = self.login('logout-no-refresh@example.com', 'sUp3rS3cr3t')
        self.client.cookies['refresh_token'] = ''
        response = self.client.post('/api/logout/', format='json')
        self.assertEqual(response.status_code, 400)