from rest_framework.throttling import AnonRateThrottle


class VerifyOTPThrottle(AnonRateThrottle):
    scope = "verify_otp"