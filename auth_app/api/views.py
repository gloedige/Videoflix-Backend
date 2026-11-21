import logging

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from auth_app.api.authentication import CookieJWTAuthentication
from auth_app.email import send_activation_email, send_password_reset_email
from auth_app.models import CustomUser
from auth_app.utils import generate_otp
from core.settings import CUSTOM_ACCESS_COOKIE_LIFETIME, CUSTOM_REFRESH_COOKIE_LIFETIME

from .serializers import (
    LoginSerializer,
    PasswordResetSerializer,
    RegistrationSerializer,
    VerifyOTPSerializer,
)

logger = logging.getLogger(__name__)

PUBLIC_PERMISSIONS = (AllowAny,)
AUTHENTICATED_PERMISSIONS = (IsAuthenticated,)

def set_auth_cookies(response, access_token, new_refresh_token):
    if access_token:
        response.set_cookie(
            key='access_token',
            value=access_token,
            max_age=CUSTOM_ACCESS_COOKIE_LIFETIME,
            httponly=True,
            secure=True,
            samesite='Lax',
            path='/',
        )

    if new_refresh_token:
        response.set_cookie(
            key='refresh_token',
            value=new_refresh_token,
            max_age=CUSTOM_REFRESH_COOKIE_LIFETIME,
            httponly=True,
            secure=True,
            samesite='Lax',
            path='/',
        )
    return response

def delete_session_cookies(response):
    response.delete_cookie('access_token', path='/')
    response.delete_cookie('refresh_token', path='/')
    return response

class VerifyOTPView(APIView):
    """API view for verifying OTP during registration."""
    permission_classes = PUBLIC_PERMISSIONS
    authentication_classes = (CookieJWTAuthentication,)
    serializer_class = VerifyOTPSerializer

    def get(self, request, **kwargs):
        serializer = self.serializer_class(data=kwargs)
        if not serializer.is_valid():
            return Response(
                serializer.errors, 
                status=status.HTTP_400_BAD_REQUEST
                )

        try:
            uid = serializer.validated_data.get('uidb64')
        except Exception as e:
            logger.error("Failed to decode UID: %s", e)
            return Response({'message': 'Activation failed.'}, status=status.HTTP_400_BAD_REQUEST)

        try:    
            user = CustomUser.objects.get(
                pk=uid, 
                otp=serializer.validated_data.get('token')
                )
        except CustomUser.DoesNotExist as e:
            logger.error("Failed to get user: %s", e)
            return Response({'message': 'Activation failed.'}, status=status.HTTP_400_BAD_REQUEST)
        
        user.is_verified = True
        user.otp = None
        user.save(update_fields=['is_verified', 'otp'])
        return Response({'message': 'Account successfully activated.'}, status=status.HTTP_200_OK)


class RegistrationView(APIView):
    """ API view for user registration. """
    permission_classes = PUBLIC_PERMISSIONS
    authentication_classes = (CookieJWTAuthentication,)

    def post(self, request):
        """Handle user registration."""
        serializer = RegistrationSerializer(data=request.data)

        if serializer.is_valid():
            try:
                with transaction.atomic():
                    user = serializer.save()
                    user.otp = generate_otp()
                    user.save()
                    send_activation_email(user.email, user.pk, user.otp)
            except IntegrityError:
                logger.exception("Fehler bei der Registrierung")
                return Response(
                    {"detail": "A user with this username or email already exists."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                        {
                            'user': {
                                'id': user.pk,
                                'email': user.email,
                            },
                            'token': user.otp
                        },
                        status=status.HTTP_201_CREATED,
                    )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CookieTokenObtainPairView(TokenObtainPairView):
    """API view for obtaining JWT tokens and setting them as HttpOnly cookies."""
    permission_classes = PUBLIC_PERMISSIONS
    serializer_class = LoginSerializer
    authentication_classes = ()

    def get_valid_login_serializer(self, data):
        serializer = self.get_serializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed:
            raise AuthenticationFailed("Invalid login data.")
        return serializer

    def post(self, request, *args, **kwargs):
        """Handle user login and set JWT tokens as HttpOnly cookies."""
        serializer = self.get_valid_login_serializer(request.data)

        user = serializer.user
        response = Response(
            {
                'detail': 'Login successfully!',
                'user': {
                    'id': user.pk,
                    'username': user.email,
                },
            },
            status=status.HTTP_200_OK,
        )
        data = serializer.validated_data
        return set_auth_cookies(response, data['access'], data['refresh'])

class CookieRefreshView(TokenRefreshView):
    """API view for refreshing JWT tokens using HttpOnly cookies."""
    permission_classes = PUBLIC_PERMISSIONS
    authentication_classes = (CookieJWTAuthentication,)
    serializer_class = TokenRefreshSerializer
    
    def post(self, request, *args, **kwargs):
        """Handle refreshing of JWT tokens using the refresh token from HttpOnly cookies."""
        refresh_token = request.COOKIES.get('refresh_token')
        access_token = request.COOKIES.get('access_token')

        if refresh_token is None:
            return self.respond_with_token_error()
        
        serializer = self.get_valid_refresh_serializer(refresh_token)
        if serializer is None:
            return self.respond_with_token_error()

        response = Response(
            {"detail": "Token refreshed",
             'access': access_token,
            }, 
            status=status.HTTP_200_OK)
        response = delete_session_cookies(response)
        data = serializer.validated_data
        return set_auth_cookies(response, data.get('access'), data.get('refresh'))

    def get_valid_refresh_serializer(self, token):
        """Validate refresh token and return its serializer, or None."""
        serializer = self.get_serializer(data={'refresh': token})
        try:
            self.check_user_active(token)
            serializer.is_valid(raise_exception=True)
        except (TokenError, AuthenticationFailed):
            return None
        return serializer

    def respond_with_token_error(self):
        """Respond with a token error indicating the refresh token is invalid or not provided."""
        return Response(
                {"detail": "Refresh token invalid or not provided"}, 
                status=status.HTTP_401_UNAUTHORIZED
                )

    def check_user_active(self, refresh_token):
        """Check if the user associated with the refresh token is active."""
        token = RefreshToken(refresh_token)
        user_id = token.payload.get('user_id')
        if not CustomUser.objects.filter(pk=user_id, is_active=True).exists():
            raise TokenError('User is inactive')

class CookieLogoutView(APIView):
    """API view for logging out users by blacklisting the refresh token and deleting cookies."""
    permission_classes = AUTHENTICATED_PERMISSIONS
    authentication_classes = (CookieJWTAuthentication,)

    def authenticate_access_cookie(self, request):
        """Validate the access cookie and return its verified JWT payload."""
        result = CookieJWTAuthentication().authenticate_access_cookie(request)
        if result is None:
            raise AuthenticationFailed('Access token is required.')
        return result[1]

    def post(self, request):
        """Handle user logout by blacklisting the refresh token and deleting HttpOnly cookies."""
        access_token = self.authenticate_access_cookie(request)
        self.blacklist_refresh_cookie(request.COOKIES.get('refresh_token'))
        CookieJWTAuthentication().store_access_token_in_custom_storage(access_token)
        CookieJWTAuthentication().clear_deprecated_access_token()
        response = Response(
            {"detail": "Log-Out successfully! All Tokens will be deleted. Refresh token is now invalid."}, 
            status=status.HTTP_200_OK)
        delete_session_cookies(response)
        return response


    def blacklist_refresh_cookie(self, refresh_token):
        """Blacklist a valid refresh cookie; tolerate its absence or invalidity."""
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            return None

class PasswordResetView(APIView):
    """API view for handling password reset requests."""
    permission_classes = PUBLIC_PERMISSIONS
    authentication_classes = ()
    serializer_class = PasswordResetSerializer

    def post(self, request, **kwargs):
        """Handle password reset request."""

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        email = serializer.validated_data.get('email')
        logger.info(f"Password reset requested for email: {email}")
        try:
            with transaction.atomic():
                user = CustomUser.objects.get(email=email)
                user.otp = generate_otp()  # Assuming you have a function to generate OTP
                user.save()
                send_password_reset_email(email, user.id, user.otp)
        except IntegrityError:
                logger.exception("Error during password reset")
                return Response(
                    {"detail": "Error occurred during password reset."},
                    status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"detail": "An email has been sent to reset your password."},
            status=status.HTTP_200_OK
        )

class PasswordResetConfirmView(APIView):
    """API view for handling password reset confirmation."""
    permission_classes = PUBLIC_PERMISSIONS
    authentication_classes = ()
    serializer_class = VerifyOTPSerializer

    def post(self, request, **kwargs):
        """Handle password reset confirmation."""
        serializer = self.serializer_class(data=kwargs)

        if not serializer.is_valid():
            logger.error("Invalid serializer data: %s", serializer.errors)
            return Response(
                serializer.errors, 
                status=status.HTTP_400_BAD_REQUEST
                )
        
        if not self.validate_confirmed_password(request):
            return Response(
                {"detail": "Passwords do not match."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                user = CustomUser.objects.get(
                    id=serializer.validated_data.get('uidb64'), 
                    otp=serializer.validated_data.get('token')
                    )
                user.set_password(request.data.get('new_password'))
                user.otp = None
                user.save()
        except (CustomUser.DoesNotExist, IntegrityError):
            logger.exception("Error during password reset confirmation")
            return Response(
                {"detail": "Error occurred during password reset confirmation."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"detail": "Password has been reset successfully."},
            status=status.HTTP_200_OK
        )

    def validate_confirmed_password(self, request):
        """Validate that the new password and confirmed password match."""
        new_password = request.data.get('new_password')
        confirm_password = request.data.get('confirm_password')
        return new_password == confirm_password
    