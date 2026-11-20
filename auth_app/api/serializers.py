import logging

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from auth_app.models import CustomUser
from auth_app.utils import decode_uidb64

logger = logging.getLogger(__name__)

User = get_user_model()


class CustomUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = (
            "id",
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
            "is_verified",
            "otp",
        )




class RegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration, including password confirmation."""

    email = serializers.EmailField(required=True)
    confirmed_password = serializers.CharField(write_only=True)

    class Meta:
        model = CustomUser
        fields = ["email", "password", "confirmed_password", "is_verified", "otp"]
        extra_kwargs = {
            "password": {"write_only": True},
            "email": {"write_only": True},
            "is_verified": {"write_only": True},
            "otp": {"write_only": True},
        }

    def validate_email(self, value):
        """Trim and normalize the email, and reject duplicates."""
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email is already in use")
        return value

    def validate(self, attrs):
        """Ensure the confirmed password matches the original password."""
        password = attrs.get("password")
        confirmed_password = attrs.get("confirmed_password")
        if password and confirmed_password and password != confirmed_password:
            raise serializers.ValidationError(
                {"confirmed_password": "Passwords do not match"}
            )
        return attrs

    def save(self):
        """Create and save a new user account with the validated data."""
        try:
            pw = self.validated_data["password"]
            account = CustomUser(
                username=self.validated_data["email"],
                email=self.validated_data["email"],
                is_verified=self.validated_data.get("is_verified", False),
                otp=self.validated_data.get("otp"),
            )
            account.set_password(pw)
            account.save()
            return account
        except KeyError:
            raise serializers.ValidationError("Password is required")


class VerifyOTPSerializer(serializers.Serializer):
    """Serializer for verifying OTP."""

    uidb64 = serializers.CharField(required=True)
    token = serializers.CharField(required=True)

    class Meta:
        model = CustomUser
        fields = ["uidb64", "token"]

    def validate_uidb64(self, value):
        """Ensure the UID is valid and decodable."""
        try:
            decoded_user_id = decode_uidb64(value)
            return int(decoded_user_id)
        except (TypeError, ValueError, OverflowError):
            raise serializers.ValidationError("Invalid UID")

    def validate(self, attrs):
        """Ensure the OTP is valid for the given user ID."""
        if not CustomUser.objects.filter(
            pk=attrs["uidb64"],
            otp=attrs["token"],
        ).exists():
            raise serializers.ValidationError({"token": "Invalid OTP"})
        return attrs


class LoginSerializer(TokenObtainPairSerializer):
    """Serializer for user login."""

    class Meta:
        model = CustomUser
        fields = ["email", "password"]
        extra_kwargs = {"password": {"write_only": True}}

    def __init__(self, *args, **kwargs):
        """Make credentials optional at field level for custom missing-field validation."""
        super().__init__(*args, **kwargs)
        self.fields["email"].required = False
        self.fields["password"].required = False

    def validate(self, attrs):
        """
        Validate the login credentials.
        """
        email = attrs.get("email")
        password = attrs.get("password")

        if not email or not password:
            raise AuthenticationFailed("Email and password are required")

        return super().validate(attrs)

class PasswordResetSerializer(serializers.Serializer):
    """Serializer for password reset requests."""

    email = serializers.EmailField(required=True)

    class Meta:
        model = CustomUser
        fields = ["email"]

    def validate_email(self, value):
        """Ensure the email exists in the system."""
        value = value.strip().lower()
        if not CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("User with this email does not exist")
        return value