import logging
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from auth_app.utils import encode_user_id

logger = logging.getLogger(__name__)

LOGO_CID = 'videoflix-logo'
LOGO_PATH = Path(__file__).resolve().parent / 'static' / 'auth_app' /'videoflix-logo.svg'

def send_activation_email(target_email, user_id, otp):
    '''Send an OTP email to the target email address for email verification.'''
    activation_link = _build_activation_link(user_id, otp)
    username = _extract_username_from_email(target_email)
    subject = 'Confirm your email'
    to = target_email
    message_content = f'Hello {username},\n\nThank you for registering with Videoflix.\n\nTo complete your registration, please verify your email address, please click the activation link below.\n\nActivation link: {activation_link}'
    html_content = _get_html_content(activation_link, username, 'activate')
  
    _send_email(subject, message_content, html_content, to)
    logger.info(f"ACTIVATION LINK {activation_link} for {target_email}") # TODO: only for development

def send_password_reset_email(target_email, user_id, otp):
    '''Send an OTP email to the target email address for password reset.'''
    reset_link = _build_reset_link(user_id, otp)
    username = _extract_username_from_email(target_email)
    subject = 'Reset your Password'
    to = target_email
    message_content = f'Hello {username},\n\nWe recently received a request to reset your password.\n\nIf you made this request, please click on the following link to reset your password:\n\n{reset_link}'
    html_content = _get_html_content(reset_link, username, 'reset')

    _send_email(subject, message_content, html_content, to)
    logger.warning(f"PASSWORD RESET LINK {reset_link} for {target_email}") # TODO: only for development


def _build_activation_link(user_id, otp):
    '''Build the activation link for email verification using the user ID and OTP.'''
    uidb64 = encode_user_id(user_id)
    frontend_activate_path = '/pages/auth/activate.html'
    return f"{settings.FRONTEND_AUTH_URL}{frontend_activate_path}?uid={uidb64}&token={otp}"

def _build_reset_link(user_id, otp):
    '''Build the password reset link using the user ID and OTP.'''
    uidb64 = encode_user_id(user_id)
    frontend_reset_path = '/pages/auth/confirm_password.html'
    return f"{settings.FRONTEND_AUTH_URL}{frontend_reset_path}?uid={uidb64}&token={otp}"

def _extract_username_from_email(email):
    '''Extract the user name from the given email address.'''
    if not email or '@' not in email:
        return None
    return email.split('@')[0]

def _send_email(subject, message_content, html_content, to):
    '''Send an email with both plain text and HTML content.'''
    from_email = settings.DEFAULT_FROM_EMAIL
    message = EmailMultiAlternatives(subject, message_content, from_email, [to])
    message.attach_alternative(html_content, "text/html")
    message.send(fail_silently=False)

def _get_html_content(link, username, auth_type):
    '''Generate the HTML content for the activation or reset email.'''
    return render_to_string(
        f'auth_app/{auth_type}_email.html', 
        context={
            'logo_cid': LOGO_CID,
            f'{auth_type}_link': link,
            'username': username,
        }
    )