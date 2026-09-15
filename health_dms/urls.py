"""
Root URL configuration for the health_dms project.

- "" (root)         -> core app: login, logout, profile, user management,
                        geography management, audit log (app_name="core")
- "dashboard/"       -> dashboard app: all 5 dashboards, CRUD, exports,
                        bulk upload (app_name="dashboard")
- "admin/"           -> Django admin
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(pattern_name="dashboard:overview", permanent=False), name="root_redirect"),
    path("", include("core.urls")),
    path("dashboard/", include("dashboard.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
