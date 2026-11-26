from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from auth_app.models import CustomUser as User


class RefreshAccessTokenTests(TestCase):
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

    def validate_refresh_token_on_blacklist(self, refresh_token):
            """Assert that the refresh token is blacklisted."""
            self.assertTrue(OutstandingToken.objects.filter(token=refresh_token).exists())
            self.assertTrue(BlacklistedToken.objects.filter(token__token=refresh_token).exists())

    def validate_token_cookies(self, response, refresh_expected=True):
            """Assert that the response sets non-empty JWT cookies."""
            self.assertIn('access_token', response.cookies)
            self.assertTrue(response.cookies['access_token'].value)
            if refresh_expected:
                self.assertIn('refresh_token', response.cookies)
                self.assertTrue(response.cookies['refresh_token'].value)

    def setUserInactive(self, test_email):
            user = User.objects.get(email=test_email)
            user.is_active = False
            user.save()

    def test_refresh_without_refresh_token(self):
        """Refreshing without a refresh token should fail."""
        response = self.client.post('/api/token/refresh/', {}, format='json')
        self.assertEqual(response.status_code, 401)
        self.assertIn('detail', response.data)
    
    def test_refresh_with_malformed_refresh_token(self):
        """A malformed refresh token should be rejected."""
        self.client.cookies['refresh_token'] = 'expired-token'
        response = self.client.post('/api/token/refresh/', {}, format='json')
        self.assertEqual(response.status_code, 401)
        self.assertIn('detail', response.data)

    def test_refresh_with_valid_refresh_token(self):
        """Refreshing with a valid refresh token should succeed."""
        self.create_user('refresh@example.com', is_verified=True, otp='123456')
        login_response = self.login('refresh@example.com', 'sUp3rS3cr3t')
        refresh_token = login_response.cookies['refresh_token'].value
        self.client.cookies['refresh_token'] = refresh_token
        response = self.client.post('/api/token/refresh/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('detail', response.data)
        self.assertIn('access_token', response.cookies)
        self.assertTrue(response.cookies['access_token']['httponly'])

    def test_refresh_with_inactive_user_in_token(self):
        """Refreshing with a refresh token for an inactive user should fail."""
        self.create_user('active@example.com', is_verified=True, otp='123456')
        self.login('active@example.com', 'sUp3rS3cr3t')
        self.setUserInactive('active@example.com')
        response = self.client.post('/api/token/refresh/', {}, format='json')
        self.assertEqual(response.status_code, 401)
        self.assertIn('detail', response.data)

    def test_refresh_with_rotated_refresh_token(self):
        """Refreshing should rotate the refresh token and blacklist the old one."""
        self.create_user('rotate@example.com', is_verified=True, otp='123456')
        login_response = self.login('rotate@example.com', 'sUp3rS3cr3t')
        old_refresh_token = login_response.cookies['refresh_token'].value
        self.client.cookies['refresh_token'] = old_refresh_token
        response = self.client.post('/api/token/refresh/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        new_refresh_token = response.cookies['refresh_token'].value
        self.assertNotEqual(old_refresh_token, new_refresh_token)
        self.validate_refresh_token_on_blacklist(old_refresh_token)

    def test_refresh_token_sets_new_access_token(self):
        """Refreshing the token sets a new access token cookie."""
        self.create_user(
            'refresh@example.com', 
            is_verified=True, 
            otp='123456',
            otp_expires_at=timezone.now() + timedelta(minutes=10)
        )
        self.login('refresh@example.com', 'sUp3rS3cr3t')
        old_refresh_token = self.client.cookies['refresh_token'].value
        response = self.client.post('/api/token/refresh/', format='json')
        new_refresh_token = response.cookies['refresh_token'].value

        self.assertEqual(response.status_code, 200)
        self.validate_token_cookies(response, refresh_expected=False)
        self.assertNotEqual(old_refresh_token, new_refresh_token)

    def test_refresh_token_with_invalid_token(self):
        """Refreshing the token with an invalid token should fail."""
        self.create_user(
            'invalid-refresh@example.com', 
            is_verified=True, 
            otp='123456',
            otp_expires_at=timezone.now() + timedelta(minutes=10)
        )
        self.login('invalid-refresh@example.com', 'sUp3rS3cr3t')
        # Manually clear the refresh token cookie to simulate an invalid token
        self.client.cookies['access_token'] = 'invalid.jwt.value'
        self.client.cookies['refresh_token'] = 'invalid.jwt.value'
        response = self.client.post('/api/token/refresh/', format='json')
        self.assertEqual(response.status_code, 401)

    def test_refresh_token_without_login(self):
        """Refreshing the token without being logged in should fail."""
        response = self.client.post('/api/token/refresh/', format='json')
        self.assertEqual(response.status_code, 401)

    def test_refresh_token_with_expired_token(self):
        """Reject a signed refresh JWT whose exp claim is in the past."""
        user = self.create_user('expired@example.com', is_verified=True, otp='123456')
        refresh_token = RefreshToken.for_user(user)
        refresh_token.set_exp(lifetime=timedelta(seconds=-1))
        self.client.cookies['refresh_token'] = str(refresh_token)

        response = self.client.post('/api/token/refresh/', format='json')

        self.assertEqual(response.status_code, 401)
        self.assertIn('detail', response.data)