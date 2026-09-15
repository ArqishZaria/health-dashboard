"""
WSGI config for the health_dms project.

Exposes the WSGI callable as a module-level variable named ``application``.
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "health_dms.settings")

application = get_wsgi_application()
