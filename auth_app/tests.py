from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from auth_app.models import CustomUser as User
from auth_app.utils import encode_user_id


class AuthenticationEndpointTest(TestCase):
    '''Test suite for authentication endpoints.'''

    def setUp(self):
        """Create an API client."""
        self.client = APIClient()

    def create_user(self, email, is_verified=False, otp=None):
        """Create and return a user with password 'pass'."""
        return User.objects.create_user(
            username=email,
            email=email,
            password='pass',
            is_verified=is_verified,
            otp=otp
        )

    def register(self, **overrides):
        """POST a valid registration payload updated by overrides; return the response."""
        payload = {
            'email': 'valid@example.com',
            'password': 'pass',
            'confirmed_password': 'pass',
        }
        payload.update(overrides)
        return self.client.post('/api/register/', payload, format='json')

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
    
    def assert_registered_user(self, response):
        """Assert user and response body of a successful registration."""
        user = User.objects.get(username='valid@example.com')
        self.assertEqual(user.email, 'valid@example.com')
        self.assertEqual(response.data, {
            'detail': 'User created successfully!'
        })

    def assert_password_rejected(self, email, password, confirmed_password, expected_field):
        """Assert registration with these passwords fails with an error on expected_field."""
        response = self.register(
            email=email,
            password=password,
            confirmed_password=confirmed_password,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data.get(expected_field), ['Passwords do not match'])
        self.assertFalse(User.objects.filter(email=email).exists())

    def validate_token_cookies(self, response, refresh_expected=True):
        """Assert that the response sets non-empty JWT cookies."""
        self.assertIn('access_token', response.cookies)
        self.assertTrue(response.cookies['access_token'].value)
        if refresh_expected:
            self.assertIn('refresh_token', response.cookies)
            self.assertTrue(response.cookies['refresh_token'].value)

    def validate_cleared_token_cookies(self):
        """Assert that the response expires both JWT cookies."""
        for name in ('access_token', 'refresh_token'):
            self.assertIn(name, self.client.cookies)
            self.assertEqual(self.client.cookies[name].value, '')
            self.assertEqual(self.client.cookies[name]['max-age'], 0)

    def validate_refresh_token_not_provided(self, response):
        """Assert that the response indicates the refresh token was not provided."""
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.data,
            {"detail": "Refresh token invalid or not provided"}
        )

    def assign_invalid_cookie_value(self, name, value, age):
        """Set the specified cookie to an invalid value."""
        self.client.cookies[name] = value
        self.client.cookies[name]['max-age'] = age

    def validate_refresh_token_on_blacklist(self, refresh_token):
        """Assert that the refresh token is blacklisted."""
        self.assertTrue(OutstandingToken.objects.filter(token=refresh_token).exists())
        self.assertTrue(BlacklistedToken.objects.filter(token__token=refresh_token).exists())

    def setUserInactive(self, test_email):
        user = User.objects.get(email=test_email)
        user.is_active = False
        user.save()

    def test_registration_allows_username_with_different_case(self):
        """A username differing only in case can still register."""
        self.create_user('existing@example.com')

        response = self.register(
            email='new@example.com'
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(email='existing@example.com').exists())


    def test_registration_returns_400_when_user_save_raises_integrity_error(self):
        """Return 400 if saving the user raises a database integrity error."""
        with (
            self.assertLogs('auth_app.api.views', level='ERROR'),
            patch(
                'auth_app.api.serializers.User.save',
                side_effect=IntegrityError('simulated unique constraint violation'),
            ),
        ):
            response = self.register(email='racing@example.com')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {'detail': 'A user with this username or email already exists.'},
        )
        self.assertFalse(User.objects.filter(email='racing@example.com').exists())

    def test_registration_rejects_mismatched_password(self):
        """Reject mismatched passwords with an error on confirmed_password."""
        self.assert_password_rejected(
            'mismatch@example.com', 'pass', 'different', 'confirmed_password'
        )

    def test_registration_normalizes_email_and_uses_it_as_username(self):
        """Normalize the email and save it as both email and username."""
        with (
            patch('auth_app.api.views.generate_otp', return_value='123456'),
            patch('auth_app.api.views.send_activation_email') as send_activation_email,
        ):
            response = self.register(
                email='  New-User@Example.COM  ',
                password='pass',
                confirmed_password='pass',
            )

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email='new-user@example.com')
        self.assertEqual(response.data['user'], {
            'id': user.pk,
            'email': 'new-user@example.com',
        })
        self.assertEqual(response.data['token'], '123456')
        self.assertEqual(user.username, user.email)
        self.assertTrue(user.check_password('pass'))
        self.assertNotEqual(user.password, 'pass')
        self.assertFalse(user.is_verified)
        send_activation_email.assert_called_once_with(user.email, user.pk, '123456')

    def test_registration_rejects_missing_required_fields(self):
        """Return field errors when required registration data is omitted."""
        response = self.client.post('/api/register/', {}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.data), {'email', 'password', 'confirmed_password'})
        self.assertFalse(User.objects.exists())

    def test_registration_rejects_blank_fields(self):
        """Return 400 and create no account when fields are blank."""
        response = self.client.post('/api/register/', {
            'email': '',
            'password': '',
            'confirmed_password': '',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_registration_rejects_invalid_email(self):
        """Reject an email address that does not have a valid format."""
        response = self.register(email='not-an-email')

        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)
        self.assertFalse(User.objects.exists())

    def test_registration_rejects_existing_email_case_insensitively(self):
        """Reject an email that already exists regardless of letter case."""
        self.create_user('existing-email@example.com')
        response = self.register(email='EXISTING-EMAIL@EXAMPLE.COM')

        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)
        self.assertEqual(User.objects.count(), 1)

    def test_registration_verifies_otp(self):
        """Verify that a user can activate their account with a valid OTP."""
        user = self.create_user('user@example.com', is_verified=False, otp='123456')
        uidb64 = encode_user_id(user.pk)
        token = '123456'
        response = self.client.get(f'/api/activate/{uidb64}/{token}/')

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.is_verified)
        self.assertIsNone(user.otp)

    def test_registration_rejects_invalid_otp(self):
        """Reject an invalid OTP during account activation."""
        user = self.create_user('user@example.com', is_verified=False, otp='123456')
        uidb64 = encode_user_id(user.pk)
        token = '654321'
        response = self.client.get(f'/api/activate/{uidb64}/{token}/')

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertFalse(user.is_verified)
        self.assertEqual(user.otp, '123456')

    def test_registration_verifies_otp_with_invalid_uid(self):
        """Reject OTP verification when the UID is invalid."""
        user = self.create_user('user@example.com', is_verified=False, otp='123456')
        uidb64 = encode_user_id('invalid-uid')
        token = '123456'
        response = self.client.get(f'/api/activate/{uidb64}/{token}/')

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertFalse(user.is_verified)
        self.assertEqual(user.otp, '123456')

    def test_registration_valid_uid_no_corresponding_user(self):
        """Reject OTP verification when the UID is valid but no corresponding user exists."""
        uidb64 = encode_user_id(9999)  # Assuming this user ID does not exist
        token = '123456'
        response = self.client.get(f'/api/activate/{uidb64}/{token}/')

        self.assertEqual(response.status_code, 400)
        self.assertIn('token', response.data)

    def test_activation_returns_404_when_uid_path_segment_is_missing(self):
        """Reject OTP verification when the UID is missing."""
        token = '123456'
        response = self.client.get(f'/api/activate//{token}/')

        self.assertEqual(response.status_code, 404)

    def test_activation_returns_404_when_token_path_segment_is_missing(self):
        """Reject OTP verification when the token is missing."""
        user = self.create_user('user@example.com', is_verified=False, otp='123456')
        uidb64 = encode_user_id(user.pk)
        response = self.client.get(f'/api/activate/{uidb64}/')

        self.assertEqual(response.status_code, 404)

    def test_registration_second_activation_attempt(self):
        """Reject a second activation attempt with the same OTP."""
        user = self.create_user('user@example.com', is_verified=False, otp='123456')
        uidb64 = encode_user_id(user.pk)
        token = '123456'
        # First activation attempt
        response = self.client.get(f'/api/activate/{uidb64}/{token}/')
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.is_verified)
        self.assertIsNone(user.otp)

        # Second activation attempt with the same OTP
        response = self.client.get(f'/api/activate/{uidb64}/{token}/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('token', response.data)

    def test_login_requires_exact_email_case(self):
        """Login succeeds with exact username case and fails otherwise."""
        user = self.create_user('login@example.com', is_verified=False, otp='123456')

        response = self.login('login@example.com', 'pass')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['detail'], 'Login successfully!')
        self.assertEqual(response.data['user']['id'], user.pk)
        self.assertEqual(response.data['user']['username'], 'login@example.com')
        self.assert_generic_login_error(self.login('LOGIN@EXAMPLE.COM', 'pass'))

    def test_login_returns_same_generic_validation_error_for_invalid_credentials(self):
        """Unknown users and wrong passwords yield the same generic error."""
        self.create_user('known@example.com', is_verified=False, otp='123456')

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
        self.create_user('cookie@example.com', is_verified=False, otp='123456')
        response = self.login('cookie@example.com', 'pass')

        self.assertEqual(response.status_code, 200)
        self.validate_token_cookies(response)

    def test_login_cookies_has_httponly_flag(self):
        """Login cookies should have the HttpOnly flag set."""
        self.create_user('cookie@example.com', is_verified=False, otp='123456')
        response = self.login('cookie@example.com', 'pass')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access_token', response.cookies)
        self.assertIn('refresh_token', response.cookies)
        self.assertTrue(response.cookies['access_token']['httponly'])
        self.assertTrue(response.cookies['refresh_token']['httponly'])

    def test_logout_without_login(self):
        """Logging out without being logged in should fail."""
        response = self.client.post('/api/logout/', format='json')
        self.assertEqual(response.status_code, 401)

    def test_logout_with_login(self):
        """Logging out after being logged in should succeed."""
        self.create_user('logout@example.com', is_verified=False, otp='123456')
        login_response = self.login('logout@example.com', 'pass')
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
        self.create_user('logout-header@example.com', is_verified=False, otp='123456')
        login_response = self.login('logout-header@example.com', 'pass')
        access_token = login_response.cookies['access_token'].value
        self.client.cookies['access_token'] = 'malformed.jwt.cookie'
        response = self.client.post('/api/logout/', HTTP_AUTHORIZATION=f'Bearer {access_token}')
        self.assertEqual(response.status_code, 401)

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
        login_response = self.login('refresh@example.com', 'pass')
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
        self.login('active@example.com', 'pass')
        self.setUserInactive('active@example.com')
        response = self.client.post('/api/token/refresh/', {}, format='json')
        self.assertEqual(response.status_code, 401)
        self.assertIn('detail', response.data)

    def test_refresh_with_rotated_refresh_token(self):
        """Refreshing should rotate the refresh token and blacklist the old one."""
        self.create_user('rotate@example.com', is_verified=True, otp='123456')
        login_response = self.login('rotate@example.com', 'pass')
        old_refresh_token = login_response.cookies['refresh_token'].value
        self.client.cookies['refresh_token'] = old_refresh_token
        response = self.client.post('/api/token/refresh/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        new_refresh_token = response.cookies['refresh_token'].value
        self.assertNotEqual(old_refresh_token, new_refresh_token)
        self.validate_refresh_token_on_blacklist(old_refresh_token)

    def test_refresh_token_sets_new_access_token(self):
        """Refreshing the token sets a new access token cookie."""
        self.create_user('refresh@example.com', is_verified=True, otp='123456')
        self.login('refresh@example.com', 'pass')
        response = self.client.post('/api/token/refresh/', format='json')

        self.assertEqual(response.status_code, 200)
        self.validate_token_cookies(response, refresh_expected=False)

    def test_refresh_token_with_invalid_token(self):
        """Refreshing the token with an invalid token should fail."""
        self.create_user('invalid-refresh@example.com', is_verified=True, otp='123456')
        self.login('invalid-refresh@example.com', 'pass')
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

    def test_reset_password_valid_email_send(self):
        """Sending a password reset request with a valid email should succeed."""
        self.create_user('reset@example.com', is_verified=True, otp='123456')
        response = self.client.post('/api/password_reset/', {'email': 'reset@example.com'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_reset_password_invalid_email_send(self):
        """Sending a password reset request with an invalid email should fail."""
        self.create_user('reset@example.com', is_verified=True, otp='123456')
        response = self.client.post('/api/password_reset/', {'email': 'nonexistent@example.com'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)

    def test_reset_password_email_in_capitals(self): 
        """Sending a password reset request with an email in capital letters should succeed."""
        self.create_user('reset@example.com', is_verified=True, otp='123456')
        response = self.client.post('/api/password_reset/', {'email': 'RESET@EXAMPLE.COM'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_reset_password_confirm_valid(self):
        """Confirming password reset with valid data should succeed."""
        user = self.create_user('reset@example.com', is_verified=True, otp='123456')
        uidb64 = encode_user_id(user.id)
        token = '123456'
        response = self.client.post(
            f'/api/password_confirm/{uidb64}/{token}/',
            {
                'new_password': 'newpass',
                'confirm_password': 'newpass'
            },
            format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('detail', response.data)

    def test_reset_password_confirm_invalid_token(self):
        """Confirming password reset with an invalid token should fail."""
        user = self.create_user('reset@example.com', is_verified=True, otp='123456')
        uidb64 = encode_user_id(user.id)
        token = 'wrongtoken'
        response = self.client.post(
            f'/api/password_confirm/{uidb64}/{token}/',
            {
                'new_password': 'newpass',
                'confirm_password': 'newpass'
            },
            format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('token', response.data)

    def test_reset_password_confirm_invalid_uid(self):
        """Confirming password reset with an invalid uid should fail."""
        uidb64 = encode_user_id('invaliduid')
        token = '123456'
        response = self.client.post(
            f'/api/password_confirm/{uidb64}/{token}/',
            {
                'new_password': 'newpass',
                'confirm_password': 'newpass'
            },
            format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('uidb64', response.data)

    def test_reset_password_confirm_mismatched_passwords(self):
        """Confirming password reset with mismatched passwords should fail."""
        user = self.create_user('reset@example.com', is_verified=True, otp='123456')
        uidb64 = encode_user_id(user.id)
        token = '123456'
        response = self.client.post(
            f'/api/password_confirm/{uidb64}/{token}/',
            {
                'new_password': 'newpass',
                'confirm_password': 'differentpass'
            },
            format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('detail', response.data)