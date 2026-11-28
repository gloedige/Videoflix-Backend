import logging
import smtplib
import ssl
from email import encoders
from email.mime.base import MIMEBase
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from auth_app.utils import encode_user_id

logger = logging.getLogger(__name__)

LOGO_CID = 'videoflix-logo'
LOGO_PATH = Path(__file__).resolve().parent / 'static' / 'auth_app' /'videoflix-logo.png'

class EmailDeliveryError(Exception):
    '''An email could not be submitted to the SMTP server.'''


def send_activation_email(target_email, user_id, otp):
    '''Send an OTP email to the target email address for email verification.'''
    activation_link = _build_activation_link(user_id, otp)
    username = _extract_username_from_email(target_email)
    subject = 'Confirm your email'
    to = target_email
    message_content = generate_activation_email_body(activation_link, username)
    html_content = _get_html_content(activation_link, username, 'activate')
  
    _send_email(subject, message_content, html_content, to)
    if settings.DEBUG:
        logger.info(f"ACTIVATION LINK {activation_link} for {target_email}")

def generate_activation_email_body(activation_link, username):
    return (f'Hello {username},'
            f'\n\nThank you for registering with Videoflix.'
            f'To complete your registration, please verify your email address, please click the activation link below.'
            f'\n\nActivation link: {activation_link}'
            f'\n\nIf you did not create an account with us, please ignore this email.'
            f'\n\nBest regards,\nYour Videoflix Team'
            )

def send_password_reset_email(target_email, user_id, otp):
    '''Send an OTP email to the target email address for password reset.'''
    reset_link = _build_reset_link(user_id, otp)
    username = _extract_username_from_email(target_email)
    subject = 'Reset your Password'
    to = target_email
    message_content = generate_password_reset_message(reset_link, username)
    html_content = _get_html_content(reset_link, username, 'reset')
    _send_email(subject, message_content, html_content, to)
    if settings.DEBUG:
        logger.info(f"PASSWORD RESET LINK {reset_link} for {target_email}")
    

def generate_password_reset_message(reset_link, username):
    '''Generate the plain text message for password reset.'''
    return (f'Hello {username},\n\nWe recently received a request to reset your password.'
            f'\n\nIf you made this request, please click on the following link to reset your password:'
            f'\n\n{reset_link}'
            f'\n\nPlease note that for security, this link is only valid for 24 hours.'
            f'\n\nIf you did not make this request, please ignore this email.'
            f'\n\nBest regards,\nYour Videoflix Team'
            )

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
    logo = get_logo_attachment()
    message.attach(logo)

    try:
        message.send(fail_silently=False)
    except (smtplib.SMTPException, ssl.SSLError, OSError) as exc:
        raise EmailDeliveryError('Failed to send email through SMTP.') from exc

def get_logo_attachment():
    '''Get the logo attachment for the email.'''
    with LOGO_PATH.open('rb') as logo_file:
        logo = MIMEBase('image', 'png')
        logo.set_payload(logo_file.read())
    encoders.encode_base64(logo)
    logo.add_header('Content-ID', f'<{LOGO_CID}>')
    logo.add_header('Content-Disposition', 'inline', filename=LOGO_PATH.name)
    return logo

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