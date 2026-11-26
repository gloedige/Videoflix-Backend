from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from auth_app.models import CustomUser as User
from auth_app.utils import encode_user_id


class ResetPasswordTests(TestCase):
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

    def test_reset_password_valid_email_send(self):
        """Sending a password reset request with a valid email should succeed."""
        self.create_user('reset@example.com', is_verified=True, otp='123456')
        response = self.client.post('/api/password_reset/', {'email': 'reset@example.com'}, format='json')
        self.assertEqual(response.status_code, 200)
    
    def test_reset_password_invalid_email_send(self):
        """Sending a password reset request with an invalid email should fail."""
        self.create_user('reset@example.com', is_verified=True, otp='123456')
        response = self.client.post('/api/password_reset/', {'email': 'nonexistent@example.com'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('detail', response.data)

    def test_reset_password_email_in_capitals(self): 
        """Sending a password reset request with an email in capital letters should succeed."""
        self.create_user('reset@example.com', is_verified=True, otp='123456')
        response = self.client.post('/api/password_reset/', {'email': 'RESET@EXAMPLE.COM'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_reset_password_confirm_valid(self):
        """Confirming password reset with valid data should succeed."""
        user = self.create_user(
            'reset@example.com', 
            is_verified=True, 
            otp='123456',
            otp_expires_at=timezone.now() + timedelta(minutes=10)
        )
        uidb64 = encode_user_id(user.id)
        token = '123456'
        response = self.client.post(
            f'/api/password_confirm/{uidb64}/{token}/',
            {
                'new_password': 'sUp3rS3cr3t',
                'confirm_password': 'sUp3rS3cr3t'
            },
            format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('detail', response.data)

    def test_reset_password_confirm_invalid_token(self):
        """Confirming password reset with an invalid token should fail."""
        user = self.create_user(
            'reset@example.com', 
            is_verified=True, 
            otp='123456', 
            otp_expires_at=timezone.now() + timedelta(minutes=10)
            )

        uidb64 = encode_user_id(user.id)
        token = 'wrongtoken'
        response = self.client.post(
            f'/api/password_confirm/{uidb64}/{token}/',
            {
                'new_password': 'sUp3rS3cr3t',
                'confirm_password': 'sUp3rS3cr3t'
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
                'new_password': 'sUp3rS3cr3t',
                'confirm_password': 'sUp3rS3cr3t'
            },
            format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('uidb64', response.data)

    def test_reset_password_confirm_mismatched_passwords(self):
        """Confirming password reset with mismatched passwords should fail."""
        user = self.create_user('reset@example.com', is_verified=True, otp='123456', otp_expires_at=timezone.now() + timedelta(minutes=10))
        uidb64 = encode_user_id(user.id)
        token = '123456'
        response = self.client.post(
            f'/api/password_confirm/{uidb64}/{token}/',
            {
                'new_password': 'sUp3rS3cr3t',
                'confirm_password': 'differentpass'
            },
            format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('confirm_password', response.data)

    def test_reset_password_confirm_expired_otp(self):
        """Confirming password reset with an expired OTP should fail."""
        user = self.create_user(
            'reset@example.com', 
            is_verified=True, 
            otp='123456', 
            otp_expires_at=timezone.now() + timedelta(hours=-1))
        uidb64 = encode_user_id(user.id)
        token = '123456'
        response = self.client.post(
            f'/api/password_confirm/{uidb64}/{token}/',
            {
                'new_password': 'sUp3rS3cr3t',
                'confirm_password': 'sUp3rS3cr3t'
            },
            format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('token', response.data)

    def test_reset_password_confirm_not_expired_otp(self):
        """Confirming password reset with a valid OTP should succeed."""
        user = self.create_user(
            'reset@example.com', 
            is_verified=True, 
            otp='123456', 
            otp_expires_at=timezone.now() + timedelta(hours=1))
        uidb64 = encode_user_id(user.id)
        token = '123456'
        response = self.client.post(
            f'/api/password_confirm/{uidb64}/{token}/',
            {
                'new_password': 'sUp3rS3cr3t',
                'confirm_password': 'sUp3rS3cr3t'
            },
            format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('detail', response.data)

    def test_reset_password_new_password_success(self):
        """Setting a new password after confirming should succeed."""
        user = self.create_user(
            'newpass@example.com', 
            is_verified=True, 
            otp='123456', 
            otp_expires_at=timezone.now() + timedelta(hours=1))
        uidb64 = encode_user_id(user.id)
        token = '123456'
        self.client.post(
            f'/api/password_confirm/{uidb64}/{token}/',
            {
                'new_password': 'NewSUp3rS3cr3t',
                'confirm_password': 'NewSUp3rS3cr3t'
            },
            format='json'
        )
        response = self.login('newpass@example.com', 'NewSUp3rS3cr3t')
        self.assertEqual(response.status_code, 200)
        self.assertIn('detail', response.data)

    def test_reset_password_old_password_failure(self):
        """Logging in with the old password after resetting should fail."""
        user = self.create_user(
            'oldpass@example.com', 
            is_verified=True, 
            otp='123456', 
            otp_expires_at=timezone.now() + timedelta(hours=1))
        uidb64 = encode_user_id(user.id)
        token = '123456'
        self.client.post(
            f'/api/password_confirm/{uidb64}/{token}/',
            {
                'new_password': 'NewSUp3rS3cr3t',
                'confirm_password': 'NewSUp3rS3cr3t'
            },
            format='json'
        )
        response = self.login('oldpass@example.com', 'sUp3rS3cr3t')
        self.assertEqual(response.status_code, 401)
        self.assertIn('detail', response.data)