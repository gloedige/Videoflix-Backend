from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from auth_app.models import CustomUser as User
from auth_app.utils import encode_user_id


class RegistrationTest(TestCase):
    """Test the user registration endpoint."""
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

    def register(self, **overrides):
            """POST a valid registration payload updated by overrides; return the response."""
            payload = {
                'email': 'valid@example.com',
                'password': 'sUp3rS3cr3t',
                'confirmed_password': 'sUp3rS3cr3t',
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
    
    def test_registration_denys_email_with_different_case(self):
            """Deny registration if the email differs only in case from an existing user."""
            self.create_user(
                email='existing@example.com',
                is_verified=True,
            )
    
            response = self.register(
                email='EXISTING@example.com',
            )
    
            self.assertEqual(response.status_code, 400)
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
            'mismatch@example.com', 'sUp3rS3cr3t', 'different', 'confirmed_password'
        )

    def test_registration_normalizes_email_and_uses_it_as_username(self):
        """Normalize the email and save it as both email and username."""
        with (
            patch('auth_app.api.views.generate_otp', return_value='123456'),
            patch('auth_app.api.views.send_activation_email') as send_activation_email,
        ):
            response = self.register(
                email='  New-User@Example.COM  ',
                password='sUp3rS3cr3t',
                confirmed_password='sUp3rS3cr3t',
            )

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email='new-user@example.com')
        self.assertEqual(response.data['user'], {
            'id': user.pk,
            'email': 'new-user@example.com',
        })
        self.assertEqual(response.data['token'], '123456')
        self.assertEqual(user.username, user.email)
        self.assertTrue(user.check_password('sUp3rS3cr3t'))
        self.assertNotEqual(user.password, 'sUp3rS3cr3t')
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
        user = self.create_user(
            'user@example.com', 
            is_verified=False, 
            otp='123456',
            otp_expires_at=timezone.now() + timedelta(hours=1)
        )
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