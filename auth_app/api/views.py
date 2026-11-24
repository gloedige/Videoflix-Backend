import logging

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
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
from auth_app.utils import check_otp_not_expired, generate_otp, get_otp_expiration_time
from core.settings import (
    AUTH_COOKIE_SECURE,
    CUSTOM_ACCESS_COOKIE_LIFETIME,
    CUSTOM_REFRESH_COOKIE_LIFETIME,
)

from .serializers import (
    LoginSerializer,
    PasswordResetConfirmSerializer,
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
            secure=AUTH_COOKIE_SECURE,
            samesite='Lax',
            path='/',
        )

    if new_refresh_token:
        response.set_cookie(
            key='refresh_token',
            value=new_refresh_token,
            max_age=CUSTOM_REFRESH_COOKIE_LIFETIME,
            httponly=True,
            secure=AUTH_COOKIE_SECURE,
            samesite='Lax',
            path='/',
        )
    return response

def delete_session_cookies(response):
    response.delete_cookie('access_token', path='/')
    response.delete_cookie('refresh_token', path='/')
    return response

def fetch_user(serializer):
        '''Fetch the user based on the UID and OTP token from the serializer.'''
        return CustomUser.objects.get(
                pk=serializer.validated_data.get('uidb64'), 
                otp=serializer.validated_data.get('token')
                )

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
            user = fetch_user(serializer)
        except CustomUser.DoesNotExist as e:
            logger.error("Failed to get user: %s", e)
            return Response(
                {'message': 'Activation failed.'}, 
                status=status.HTTP_400_BAD_REQUEST
                )

        try:
            self.check_and_activate_user(user)
        except ValidationError as e:
            logger.error("Failed to activate user: %s", e)
            return Response(
                {'message': 'Activation failed.'}, 
                status=status.HTTP_400_BAD_REQUEST
                )

        return Response(
            {'message': 'Account successfully activated.'}, 
            status=status.HTTP_200_OK
            )
        

    def check_and_activate_user(self, user):
        '''Check if the OTP is still valid and activate the user if it is.'''

        with transaction.atomic():
            if check_otp_not_expired(user.otp_expires_at):    
                user.is_verified = True
                user.otp = None
                user.otp_expires_at = None
                user.save(update_fields=['is_verified', 'otp', 'otp_expires_at'])
            else:
                raise ValidationError("OTP has expired.")

class RegistrationView(APIView):
    ''' API view for user registration. '''
    permission_classes = PUBLIC_PERMISSIONS
    authentication_classes = (CookieJWTAuthentication,)
    serializer_class = RegistrationSerializer

    def post(self, request):
        '''Handle user registration.'''
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            logger.error("Registration failed due to invalid data: %s", serializer.errors)
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
                user.otp_expires_at = get_otp_expiration_time()
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
        if not user.is_verified:
            logger.error("User not verified: %s", user.email)
            raise AuthenticationFailed("Invalid login data.")
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
    authentication_classes = ()
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
    throttle_classes = (VerifyOTPThrottle,)

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
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            user = None
        
        if user is not None:
            try:
                with transaction.atomic():
                    user.otp = generate_otp()
                    user.otp_expires_at = get_otp_expiration_time()
                    user.save()
                    send_password_reset_email(email, user.id, user.otp)
            except IntegrityError:
                logger.exception("Error during password reset")

        return Response(
            {"detail": "An email has been sent to reset your password."},
            status=status.HTTP_200_OK
        )
    
class PasswordResetConfirmView(APIView):
    '''API view for handling password reset confirmation.'''
    permission_classes = PUBLIC_PERMISSIONS
    authentication_classes = ()
    serializer_class = PasswordResetConfirmSerializer

    def post(self, request, **kwargs):

        serializer = self.serializer_class(data={
            'uidb64': kwargs.get('uidb64'),
            'token': kwargs.get('token'),
            'new_password': request.data.get('new_password'),
            'confirm_password': request.data.get('confirm_password')
        })

        if not serializer.is_valid():
            logger.error("Password reset confirmation failed: invalid data")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        return Response(
            {"detail": "Password has been reset successfully."},
            status=status.HTTP_200_OK
        )