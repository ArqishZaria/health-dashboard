from core.permissions import scope_queryset_by_geography
from django.db.models import Q


def scope_qs(user, queryset, region_field="region", local_council_field="local_council"):
    return scope_queryset_by_geography(user, queryset, region_field, local_council_field)


def scope_budget_qs(user, queryset):
    """
    BudgetAllocation has no local_council; allocations can be national-level
    (region is null) or region-level. Scope accordingly:
      - National: sees everything.
      - Regional: sees their region's allocations + national-level ones.
      - Local/DataEntry/Viewer with a local council: sees their region's
        allocations (via local_council.region) + national-level ones.
    """
    if user.is_superuser or user.is_national:
        return queryset
    if user.role == user.Role.REGIONAL and user.region_id:
        return queryset.filter(Q(region_id=user.region_id) | Q(region__isnull=True))
    if user.local_council_id:
        return queryset.filter(Q(region_id=user.local_council.region_id) | Q(region__isnull=True))
    if user.region_id:
        return queryset.filter(Q(region_id=user.region_id) | Q(region__isnull=True))
    return queryset.none()


def month_label(dt):
    return dt.strftime("%b %Y") if dt else "Unknown"
