from django.utils.http import urlsafe_base64_encode
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_bytes
from django.utils.encoding import force_str



def encode_user_id(user):
    user_id = user.pk  # Oder die UUID des Users (z. B. user.id)
    
    uidb64 = urlsafe_base64_encode(force_bytes(user_id))
    print(uidb64)  # Gibt einen sicheren Base64-String aus (ohne Zeichen wie '+', '/' oder '=')
    return uidb64

def decode_user_id(uidb64):
    # Den Base64-String wieder zurückverwandeln
    user_id = force_str(urlsafe_base64_decode(uidb64))
    return user_id