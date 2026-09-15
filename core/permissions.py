"""
Role-based access-control helpers shared across the project.

Scoping rule of thumb:
  NATIONAL              -> unrestricted queryset
  REGIONAL              -> queryset filtered to user's Region
  LOCAL / DATA_ENTRY     -> queryset filtered to user's Local Council
  VIEWER                -> same scoping as REGIONAL/LOCAL depending on assignment
"""
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restrict a class-based view to a whitelist of roles."""
    allowed_roles = ()  # e.g. ("NATIONAL", "REGIONAL")
    raise_exception = True

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if not self.allowed_roles:
            return True
        return user.role in self.allowed_roles

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            # Temporarily disable raise_exception so AccessMixin redirects to
            # LOGIN_URL instead of raising 403 for anonymous visitors.
            self.raise_exception = False
            try:
                return super().handle_no_permission()
            finally:
                self.raise_exception = True
        raise PermissionDenied("You do not have permission to access this page.")


class NationalOnlyMixin(RoleRequiredMixin):
    allowed_roles = ("NATIONAL",)


def scope_queryset_by_geography(user, queryset, region_field="region", local_council_field="local_council"):
    """
    Given a queryset whose model has (directly or via lookup path) a region
    and/or local_council field, restrict it according to the user's role.
    `region_field` / `local_council_field` accept Django lookup paths, e.g.
    "participant__region".
    """
    if user.is_superuser or user.is_national:
        return queryset
    if user.role == user.Role.REGIONAL and user.region_id:
        return queryset.filter(**{region_field: user.region_id})
    if user.role in (user.Role.LOCAL, user.Role.DATA_ENTRY) and user.local_council_id:
        return queryset.filter(**{local_council_field: user.local_council_id})
    if user.role == user.Role.VIEWER:
        if user.region_id:
            return queryset.filter(**{region_field: user.region_id})
        if user.local_council_id:
            return queryset.filter(**{local_council_field: user.local_council_id})
    # No scope assigned -> no data visible (safe default)
    return queryset.none()
