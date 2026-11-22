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
from auth_app.api.throttling import VerifyOTPThrottle
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
    throttle_classes = (VerifyOTPThrottle,)

    def get(self, request, **kwargs):
        '''Handle GET request for OTP verification during registration.'''
        serializer = self.serializer_class(data=kwargs)

        if not serializer.is_valid():
            return Response(
                serializer.errors, 
                status=status.HTTP_400_BAD_REQUEST
                )
        return self.activate_user(serializer)
    
    def activate_user(self, serializer):
        '''Activate the user based on the validated serializer data.'''
        try:
            user = self.fetch_user(serializer)
            user.is_verified = True
            user.otp = None
            user.save(update_fields=['is_verified', 'otp'])
        except CustomUser.DoesNotExist as e:
            logger.error("Failed to get user: %s", e)
            return Response({'message': 'Activation failed.'}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({'message': 'Account successfully activated.'}, status=status.HTTP_200_OK)

    def fetch_user(self, serializer):
        '''Fetch the user based on the UID and OTP token from the serializer.'''
        return CustomUser.objects.get(
                pk=serializer.validated_data.get('uidb64'), 
                otp=serializer.validated_data.get('token')
                )

class RegistrationView(APIView):
    ''' API view for user registration. '''
    permission_classes = PUBLIC_PERMISSIONS
    authentication_classes = (CookieJWTAuthentication,)
    serializer_class = RegistrationSerializer

    def post(self, request):
        '''Handle user registration.'''
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return Response(
                serializer.errors, 
                status=status.HTTP_400_BAD_REQUEST
                )
        
        return self.handle_registration(serializer)
    
    def handle_registration(self, serializer):
        '''Handle the registration process for a new user.
        This includes saving the user, generating an OTP,
        sending the activation email, and handling any integrity errors.
        '''
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
        return self.respond_with_user_and_token(user)

    def respond_with_user_and_token(self, user):
        '''Respond with the newly registered user and their OTP token.'''
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

class CookieTokenObtainPairView(TokenObtainPairView):
    '''API view for obtaining JWT tokens and setting them as HttpOnly cookies.'''
    permission_classes = PUBLIC_PERMISSIONS
    serializer_class = LoginSerializer
    authentication_classes = ()

    def get_valid_login_serializer(self, data):
        '''Validate login data and return the corresponding serializer.'''
        serializer = self.get_serializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed:
            raise AuthenticationFailed("Invalid login data.")
        return serializer

    def post(self, request, *args, **kwargs):
        '''Handle user login and set JWT tokens as HttpOnly cookies.'''
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
    '''API view for refreshing JWT tokens using HttpOnly cookies.'''
    permission_classes = PUBLIC_PERMISSIONS
    authentication_classes = (CookieJWTAuthentication,)
    serializer_class = TokenRefreshSerializer
    
    def post(self, request, *args, **kwargs):
        '''Handle refreshing of JWT tokens using the refresh token from HttpOnly cookies.'''
        refresh_token = request.COOKIES.get('refresh_token')
        access_token = request.COOKIES.get('access_token')

        if refresh_token is None:
            return self.respond_with_token_error()
        
        serializer = self.get_valid_refresh_serializer(refresh_token)
        if serializer is None:
            return self.respond_with_token_error()

        response = self.respond_with_token_refreshed(access_token)
        response = delete_session_cookies(response)
        data = serializer.validated_data
        return set_auth_cookies(response, data.get('access'), data.get('refresh'))

    def get_valid_refresh_serializer(self, token):
        '''Validate refresh token and return its serializer, or None.'''
        serializer = self.get_serializer(data={'refresh': token})
        try:
            self.check_user_active(token)
            serializer.is_valid(raise_exception=True)
        except (TokenError, AuthenticationFailed):
            return None
        return serializer

    def respond_with_token_error(self):
        '''Respond with a token error indicating the refresh token is invalid or not provided.'''
        return Response(
                {"detail": "Refresh token invalid or not provided"}, 
                status=status.HTTP_401_UNAUTHORIZED
                )

    def check_user_active(self, refresh_token):
        '''Check if the user associated with the refresh token is active.'''
        token = RefreshToken(refresh_token)
        user_id = token.payload.get('user_id')
        if not CustomUser.objects.filter(pk=user_id, is_active=True).exists():
            raise TokenError('User is inactive')

    def respond_with_token_refreshed(self, access_token):
        '''Respond indicating the token has been refreshed successfully.'''
        return Response(
            {"detail": "Token refreshed",
                'access': access_token,
            }, 
            status=status.HTTP_200_OK)

class CookieLogoutView(APIView):
    '''API view for logging out users by blacklisting the refresh token and deleting cookies.'''
    permission_classes = AUTHENTICATED_PERMISSIONS
    authentication_classes = (CookieJWTAuthentication,)

    def authenticate_access_cookie(self, request):
        '''Validate the access cookie and return its verified JWT payload.'''
        result = CookieJWTAuthentication().authenticate_access_cookie(request)
        if result is None:
            raise AuthenticationFailed('Access token is required.')
        return result[1]

    def post(self, request):
        '''Handle user logout by blacklisting the refresh token and deleting HttpOnly cookies.'''
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
        '''Blacklist a valid refresh cookie; tolerate its absence or invalidity.'''
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            return None

class PasswordResetView(APIView):
    '''API view for handling password reset requests.'''
    permission_classes = PUBLIC_PERMISSIONS
    authentication_classes = ()
    serializer_class = PasswordResetSerializer

    def post(self, request, **kwargs):
        '''Handle password reset request.'''
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        return self.handle_password_reset(serializer)

    def handle_password_reset(self, serializer):
        '''Handle the actual password reset logic.'''
        email = serializer.validated_data.get('email')
        try:
            with transaction.atomic():
                user = CustomUser.objects.get(email=email)
                user.otp = generate_otp()
                user.save()
                send_password_reset_email(email, user.id, user.otp)
        except IntegrityError:
            logger.exception("Error during password reset")
            return self.handle_password_reset_error()
        return Response(
            {"detail": "An email has been sent to reset your password."},
            status=status.HTTP_200_OK
        )
    
    def handle_password_reset_error(self):
        '''Handle errors during password reset.'''
        return Response(
            {"detail": "Error occurred during password reset."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
class PasswordResetConfirmView(APIView):
    '''API view for handling password reset confirmation.'''
    permission_classes = PUBLIC_PERMISSIONS
    authentication_classes = ()
    serializer_class = VerifyOTPSerializer

    def post(self, request, **kwargs):
        '''Handle password reset confirmation.'''
        serializer = self.serializer_class(data=kwargs)

        if not serializer.is_valid():
            return Response(
                serializer.errors, 
                status=status.HTTP_400_BAD_REQUEST
                )
        
        if not self.check_passwords_match(request):
            logger.error("Password reset failed: passwords do not match")
            return Response(
                {"detail": "Passwords do not match."},
                status=status.HTTP_400_BAD_REQUEST
            )

        return self.reset_password(request, serializer)

    def check_passwords_match(self, request):
        '''Validate that the new password and confirmed password match.'''
        new_password = request.data.get('new_password')
        confirm_password = request.data.get('confirm_password')
        return bool(new_password and confirm_password and new_password == confirm_password)
    
    def reset_password(self, request, serializer):
        '''Reset the user's password using the provided serializer.'''
        try:
            with transaction.atomic():
                user = self.load_user_by_uid_and_token(serializer)
                user.set_password(request.data.get('new_password'))
                user.otp = None
                user.save()
        except CustomUser.DoesNotExist:
            logger.exception("User not found during password reset confirmation")
            return self.handle_user_not_found()
        except IntegrityError:
            logger.exception("Error during password reset confirmation")
            return self.handle_integrity_error()
        return Response(
            {"detail": "Password has been reset successfully."},
            status=status.HTTP_200_OK
        )
    
    def handle_user_not_found(self):
        '''Handle the case when the user is not found.'''
        return Response(
            {"detail": "Custom user not found."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    def handle_integrity_error(self):
        '''Handle integrity errors during password reset confirmation.'''
        return Response(
            {"detail": "Error occurred during password reset confirmation."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def load_user_by_uid_and_token(self, serializer):
        '''Load the user based on the UID and OTP token from the serializer.'''
        return CustomUser.objects.get(
                    id=serializer.validated_data.get('uidb64'), 
                    otp=serializer.validated_data.get('token')
                    )