from django.db import models
from django.contrib.auth.models import AbstractUser


class CustomUser(AbstractUser):
    '''
    Custom user model extending Django's AbstractUser.
    Adds fields for email verification and OTP.
    '''
    email = models.EmailField(unique=True)
    is_verified = models.BooleanField(default=False)
    otp = models.CharField(max_length=6, blank=True, null=True)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

class AccessTokenStorage(models.Model):
    """Model to store access tokens in a custom storage mechanism."""
    access_token = models.TextField()
    expires_at = models.DateTimeField()

    class Meta:
        verbose_name = "Access Token Storage"
        verbose_name_plural = "Access Token Storages"

    def __str__(self):
        return f"AccessTokenStorage(id={self.id}, expires_at={self.expires_at})"