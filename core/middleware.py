from .models import AuditLog


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditLogMiddleware:
    """Attaches request to thread-local-ish state is overkill; instead we expose
    a small helper on request so views can easily log actions with IP context."""

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
        object_id=str(object_id),
        description=description,
        ip_address=getattr(request, "client_ip", None),
    )
