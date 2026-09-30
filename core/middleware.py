import ipaddress
from django.conf import settings
from .models import AuditLog


def _client_ip(request):
    """Returns a validated IP string or None. Never trusts
    X-Forwarded-For unless the deployment explicitly opts in (set
    TRUST_X_FORWARDED_FOR = True in settings only if you're behind a
    proxy that sanitizes/sets this header itself, e.g. nginx/ALB) -
    otherwise any client can spoof the audit trail's IP address, and a
    malformed header would previously crash login with a 500 by failing
    GenericIPAddressField validation at save time.
    """
    ip = request.META.get("REMOTE_ADDR")
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            ip = xff.split(",")[0].strip()
    try:
        ipaddress.ip_address(ip)
        return ip
    except (ValueError, TypeError):
        return None


class AuditLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.client_ip = _client_ip(request)
        response = self.get_response(request)
        return response


def log_action(request, action, model_name="", object_id="", description=""):
    user = getattr(request, "user", None)
    AuditLog.objects.create(
        user=user if user and user.is_authenticated else None,
        action=action,
        model_name=model_name,
        object_id=str(object_id) if object_id else "",
        description=description,
        ip_address=getattr(request, "client_ip", None),
    )