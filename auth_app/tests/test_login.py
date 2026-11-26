
from django.test import TestCase
from rest_framework.test import APIClient

from auth_app.models import CustomUser as User


class LoginTests(TestCase):
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

    def assert_generic_login_error(self, response):
            """Assert the response is the generic invalid-credentials 401 error."""
            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.data,
                {'detail': "Invalid login data."},
            )

    def validate_token_cookies(self, response, refresh_expected=True):
            """Assert that the response sets non-empty JWT cookies."""
            self.assertIn('access_token', response.cookies)
            self.assertTrue(response.cookies['access_token'].value)
            if refresh_expected:
                self.assertIn('refresh_token', response.cookies)
                self.assertTrue(response.cookies['refresh_token'].value)
    
    def test_login_requires_exact_email_case(self):
        """Login succeeds with exact username case and fails otherwise."""
        user = self.create_user('login@example.com', is_verified=True, otp='123456')

        response = self.login('login@example.com', 'sUp3rS3cr3t')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['detail'], 'Login successfully!')
        self.assertEqual(response.data['user']['id'], user.pk)
        self.assertEqual(response.data['user']['username'], 'login@example.com')
        self.assert_generic_login_error(self.login('LOGIN@EXAMPLE.COM', 'sUp3rS3cr3t'))

    def test_login_returns_same_generic_validation_error_for_invalid_credentials(self):
        """Unknown users and wrong passwords yield the same generic error."""
        self.create_user('known@example.com', is_verified=True, otp='123456')

        for email, password in (
            ('missing-user@example.com', 'pass'),
            ('known@example.com', 'wrong'),
        ):
            with self.subTest(email=email):
                self.assert_generic_login_error(self.login(email, password))

    def test_login_rejects_missing_fields(self):
        """Login without fields reports both missing fields."""
        response = self.client.post('/api/login/', {}, format='json')

        self.assertEqual(response.status_code, 401)

    def test_cookies_are_set_on_login(self):
        """Cookies are correctly set after a successful login."""
        self.create_user('cookie@example.com', is_verified=True, otp='123456')
        response = self.login('cookie@example.com', 'sUp3rS3cr3t')

        self.assertEqual(response.status_code, 200)
        self.validate_token_cookies(response)

    def test_login_cookies_has_httponly_flag(self):
        """Login cookies should have the HttpOnly flag set."""
        self.create_user('cookie@example.com', is_verified=True, otp='123456')
        response = self.login('cookie@example.com', 'sUp3rS3cr3t')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access_token', response.cookies)
        self.assertIn('refresh_token', response.cookies)
        self.assertTrue(response.cookies['access_token']['httponly'])
        self.assertTrue(response.cookies['refresh_token']['httponly'])

    def test_login_rejects_unverified_user(self):
        """Login should fail for users who are not verified."""
        self.create_user(
            'unverified@example.com', 
            is_verified=False, 
            otp='123456')
        response = self.login('unverified@example.com', 'sUp3rS3cr3t')
        self.assertEqual(response.status_code, 401)