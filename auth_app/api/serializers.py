import logging
from typing import ClassVar

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from auth_app.models import CustomUser
from auth_app.utils import check_otp_not_expired, decode_uidb64

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
        fields = (
            "email", 
            "password", 
            "confirmed_password"
            )
        extra_kwargs: ClassVar[dict[str, dict[str, bool]]] = {
            "password": {"write_only": True},
            "email": {"write_only": True},
        }

    def validate_email(self, value):
        """Trim and normalize the email, and reject duplicates."""
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email is already in use")
        return value

    def validate_password(self, value):
        """Ensure the password meets basic requirements."""
        if not value:
            raise serializers.ValidationError("Password is required")
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
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
        fields = ("uidb64", "token")

    def validate_uidb64(self, value):
        """Ensure the UID is valid and decodable."""
        try:
            decoded_user_id = decode_uidb64(value)
            return int(decoded_user_id)
        except (TypeError, ValueError, OverflowError, UnicodeDecodeError):
            raise serializers.ValidationError({"uidb64": "Invalid UID"})

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
        fields = ("email", "password")
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
        fields = ("email",)

    def validate_email(self, value):
        """Ensure the email has valid format."""
        return value.strip().lower()
    
class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for confirming password reset."""

    uidb64 = serializers.CharField(required=True)
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, write_only=True)
    confirm_password = serializers.CharField(required=True, write_only=True)

    def validate_uidb64(self, value):
        """Decode the URL-safe user ID before looking up the account."""
        try:
            return int(decode_uidb64(value))
        except (TypeError, ValueError, OverflowError, UnicodeDecodeError) as exc:
            raise serializers.ValidationError("Invalid UID") from exc

    def validate(self, attrs):
        """Ensure the new passwords match."""
        self.validate_passwords_match(attrs)
        user = self.get_authenticated_user(attrs)
        self.validate_user_password(attrs, user)

        attrs["user"] = user
        return attrs

    def validate_passwords_match(self, attrs):
        """Check if the new password and confirm password match."""
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match"}
            )

    def validate_user_password(self, attrs, user):
        """Validate the new password against Django's password validators."""
        try:
            validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": exc.messages}) from exc

    def get_authenticated_user(self, attrs):
        """Retrieve the user based on the UID and OTP token, raising an error if not found."""
        try:
            user = self.fetch_user(attrs)
        except CustomUser.DoesNotExist as exc:
            raise serializers.ValidationError({"token": "Invalid OTP"}) from exc
        return user

    def fetch_user(self, data):
        """Fetch the user based on the UID and OTP token from the serializer."""
        return CustomUser.objects.get(
            pk=data['uidb64'],
            otp=data.get('token')
        )
    
    def create(self, attrs):
        """Set the new password and consume the one-time reset token for the user."""
        with transaction.atomic():
            user = self.fetch_user_by_token_and_pk(attrs)

            if not check_otp_not_expired(user.otp_expires_at):
                raise serializers.ValidationError({"token": "OTP is invalid or expired"})
            
            user.set_password(attrs["new_password"])
            user.otp = None
            user.otp_expires_at = None
            user.save(update_fields=["password", "otp", "otp_expires_at"])
        return user

    def fetch_user_by_token_and_pk(self, attrs):
        """Fetch the user for password reset using the OTP token, ensuring the record is locked for update."""
        try:
            user = CustomUser.objects.select_for_update().get(
                    pk=attrs["user"].pk,
                    otp=attrs["token"],
                )
        except CustomUser.DoesNotExist as exc:
            raise serializers.ValidationError(
                    {"token": "OTP is invalid or has already been used"}
                ) from exc
            
        return user
