"""
Shared analytics helpers used across every dashboard view.
"""
import calendar
import json
from collections import OrderedDict, defaultdict
import datetime
from django.db.models import Count, Sum, Q
from django.utils import timezone

AGE_BUCKETS = [
    (0, 17, "0-17"),
    (18, 30, "18-30"),
    (31, 45, "31-45"),
    (46, 60, "46-60"),
    (61, 200, "61+"),
]

def daily_trend(queryset, date_field, date_from, date_to):
    if not date_from or not date_to:
        return monthly_trend(queryset, date_field=date_field)
    buckets = OrderedDict()
    d = date_from
    one_day = datetime.timedelta(days=1)
    while d <= date_to:
        buckets[d] = 0
        d += one_day

    rows = queryset.values(date_field).annotate(c=Count("id"))
    for row in rows:
        key = row[date_field]
        if key in buckets:
            buckets[key] = row["c"]

    labels = [d.strftime("%d %b") for d in buckets.keys()]
    values = list(buckets.values())
    return labels, values


def year_month_trend(queryset, date_field, year):
    buckets = OrderedDict((m, 0) for m in range(1, 13))
    field_year = f"{date_field}__year"
    field_month = f"{date_field}__month"
    rows = queryset.filter(**{field_year: year}).values(field_month).annotate(c=Count("id"))
    for row in rows:
        key = row[field_month]
        if key in buckets:
            buckets[key] = row["c"]

    labels = [calendar.month_abbr[m] for m in buckets.keys()]
    values = list(buckets.values())
    return labels, values


def trend_for_filters(queryset, filters, date_field="date"):
    if getattr(filters, "year", None) and getattr(filters, "month", None):
        return daily_trend(queryset, date_field, filters.date_from, filters.date_to)
    if getattr(filters, "year", None):
        try:
            year = int(filters.year)
        except (TypeError, ValueError):
            return monthly_trend(queryset, date_field=date_field)
        return year_month_trend(queryset, date_field, year)
    return monthly_trend(queryset, date_field=date_field, months_back=12)


def age_bucket_label(age):
    if age is None:
        return "Unknown"
    for low, high, label in AGE_BUCKETS:
        if low <= age <= high:
            return label
    return "Unknown"


def age_bucket_order():
    return [b[2] for b in AGE_BUCKETS] + ["Unknown"]


def pct(numerator, denominator):
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def chart_json(values):
    return (json.dumps(list(values))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def age_gender_breakdown(participant_qs):
    counts = defaultdict(lambda: defaultdict(int))
    for age, gender in participant_qs.values_list("age", "gender"):
        counts[age_bucket_label(age)][gender or "O"] += 1

    labels = age_bucket_order()
    male = [counts[label].get("M", 0) for label in labels]
    female = [counts[label].get("F", 0) for label in labels]
    other = [counts[label].get("O", 0) for label in labels]
    return labels, male, female, other


def monthly_trend(queryset, date_field="date", months_back=12):
    today = timezone.localdate()
    buckets = OrderedDict()
    year, month = today.year, today.month
    for _ in range(months_back):
        buckets[(year, month)] = 0
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    buckets = OrderedDict(reversed(list(buckets.items())))

    field_year = f"{date_field}__year"
    field_month = f"{date_field}__month"
    rows = queryset.values(field_year, field_month).annotate(c=Count("id"))
    for row in rows:
        key = (row[field_year], row[field_month])
        if key in buckets:
            buckets[key] = row["c"]

    labels = [f"{calendar.month_abbr[m]} {y}" for (y, m) in buckets.keys()]
    values = list(buckets.values())
    return labels, values


def yearly_trend(queryset, date_field="date"):
    field_year = f"{date_field}__year"
    rows = queryset.values(field_year).annotate(c=Count("id")).order_by(field_year)
    labels = [str(r[field_year]) for r in rows]
    values = [r["c"] for r in rows]
    return labels, values


def region_wise(queryset, region_field="region__name", value_field="id", agg="count"):
    if agg == "count":
        rows = queryset.values(region_field).annotate(v=Count(value_field)).order_by("-v")
    else:
        rows = queryset.values(region_field).annotate(v=Sum(value_field)).order_by("-v")
    labels = [r[region_field] or "Unspecified" for r in rows]
    values = [r["v"] or 0 for r in rows]
    return labels, values


def local_council_wise(queryset, field="local_council__name", limit=None):
    # NOTE: grouped by (local_council_id, local_council__name) so two
    # councils that share a name in different regions (e.g. "Main
    # Jamatkhana" pattern) are never merged into one bar/row.
    rows = queryset.values("local_council_id", field).annotate(v=Count("id")).order_by("-v")
    if limit:
        rows = rows[:limit]
    labels = [r[field] or "Unspecified" for r in rows]
    values = [r["v"] for r in rows]
    return labels, values


def jamat_khana_wise(queryset, field="jamat_khana__name", limit=None):
    rows = (
        queryset.exclude(jamat_khana__isnull=True)
        .values("jamat_khana_id", field)
        .annotate(v=Count("id")).order_by("-v")
    )
    if limit:
        rows = rows[:limit]
    labels = [r[field] or "Unspecified" for r in rows]
    values = [r["v"] for r in rows]
    return labels, values


def portfolio_wise(queryset, portfolio_field="portfolio__name"):
    rows = queryset.values("portfolio_id", portfolio_field).annotate(v=Count("id")).order_by("-v")
    labels = [r[portfolio_field] or "Unspecified" for r in rows]
    values = [r["v"] for r in rows]
    return labels, values


def program_wise(queryset, program_field="program__name", limit=12):
    rows = queryset.values("program_id", program_field).annotate(v=Count("id")).order_by("-v")[:limit]
    labels = [r[program_field] or "Unspecified" for r in rows]
    values = [r["v"] for r in rows]
    return labels, values


def budget_utilization(cost_total, allocated_total):
    """Low-level percent/remaining calculator - caller is responsible for
    passing cost_total and allocated_total that already cover the SAME
    fiscal year and the SAME scope. See budget_utilization_for_scope()
    below, which is the function views should call instead of computing
    cost_total/allocated_total manually."""
    utilized = cost_total or 0
    allocated = allocated_total or 0
    remaining = max(allocated - utilized, 0)
    return {
        "allocated": allocated,
        "utilized": utilized,
        "remaining": remaining,
        "percent": pct(utilized, allocated) if allocated else None,
    }


def budget_utilization_for_scope(allocations_qs, cost_querysets, fiscal_year=None):
    """
    Correct, scope-consistent Budget Utilization:
      - allocations_qs: an already role-scoped BudgetAllocation queryset
        (see dashboard.utils.scope_budget_qs).
      - cost_querysets: list of already role-scoped querysets whose `cost`
        field should count as spend against that allocation (e.g.
        [activities_qs, trainings_qs]).
      - fiscal_year: defaults to the current calendar year. Both sides of
        the comparison are filtered to this single fiscal year, so a
        multi-year allocation total is never compared against an
        all-time cost total (the previous bug).
    National-level allocations (region=None) are included alongside a
    regional user's own regional allocations, matching scope_budget_qs,
    but are only ever summed ONCE (no double counting) because
    allocations_qs is already deduplicated at the queryset level.
    """
    fiscal_year = fiscal_year or timezone.localdate().year
    allocations_qs = allocations_qs.filter(fiscal_year=fiscal_year)
    total_allocated = allocations_qs.aggregate(s=Sum("allocated_amount"))["s"] or 0

    total_cost = 0
    for qs in cost_querysets:
        date_field = "date" if hasattr(qs.model, "date") else "referral_date"
        total_cost += qs.filter(**{f"{date_field}__year": fiscal_year}).aggregate(s=Sum("cost"))["s"] or 0

    return budget_utilization(total_cost, total_allocated)