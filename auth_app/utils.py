import random

from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode


def encode_user_id(user_id):
    '''Encode the user ID into a URL-safe Base64 string.'''
    uidb64 = urlsafe_base64_encode(force_bytes(user_id))
    return uidb64

def decode_uidb64(uidb64):
    '''Decode the URL-safe Base64 string back into the user ID.'''
    user_id = force_str(urlsafe_base64_decode(uidb64))
    return user_id

def generate_otp(length=6):
    '''Generate a numeric OTP of the specified length.'''
    otp_chars = "0123456789" 
    otp = ''.join(random.SystemRandom().choice(otp_chars) for _ in range(length))
    return otp