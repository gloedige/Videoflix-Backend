from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from auth_app.models import CustomUser as User
from auth_app.utils import encode_user_id


class ActivationTests(TestCase):
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

    def test_activation_second_activation_attempt(self):
        """Reject a second activation attempt with the same OTP."""
        user = self.create_user(
            'user@example.com', 
            is_verified=False, 
            otp='123456',
            otp_expires_at=timezone.now() + timedelta(minutes=10)
            )
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

    def test_activation_with_valid_otp_expiration_time(self):
        """Reject activation attempts with expired OTPs."""
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
        self.assertIn('message', response.data)

    def test_activation_with_expired_otp(self):
        """Reject activation attempts with expired OTPs."""
        user = self.create_user(
            'user@example.com', 
            is_verified=False, 
            otp='123456', 
            otp_expires_at=timezone.now() + timedelta(hours=-1)
        )
        uidb64 = encode_user_id(user.pk)
        token = '123456'
        response = self.client.get(f'/api/activate/{uidb64}/{token}/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('message', response.data)