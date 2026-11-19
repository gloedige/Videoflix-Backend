from unittest.mock import patch

# Third-party imports
from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient

# Local imports
from auth_app.models import CustomUser as User

class AuthenticationEndpointTest(TestCase):
    '''Test suite for authentication endpoints.'''

    def setUp(self):
        """Create an API client."""
        self.client = APIClient()

    def create_user(self, email, is_active=True):
        """Create and return a user with password 'pass'."""
        return User.objects.create_user(
            username=email,
            email=email,
            password='pass',
            is_active=is_active
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