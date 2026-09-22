"""
Shared analytics helpers used across every dashboard view.

Centralising this logic keeps the "in-depth analysis" consistent between
Overview / Activity / Screening / Training / Case dashboards: the same
age-bucketing, referral-rate, trend, geography-breakdown and
budget-utilization math is used everywhere rather than re-implemented per
view.
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
    """Day-by-day counts between date_from and date_to (inclusive)."""
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
    """Jan-Dec counts for a specific year."""
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
    """
    Adaptive replacement for calling monthly_trend() directly on every
    dashboard's "Trend" chart:
      - No year selected      -> last 12 months up to the current month.
      - Year selected only    -> Jan through Dec of that year.
      - Year + month selected -> day-by-day across that specific month.
    """
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
    return json.dumps(list(values))


def age_gender_breakdown(participant_qs):
    """Returns (age_labels, male_series, female_series, other_series) aligned
    to the fixed AGE_BUCKETS order, for a diverging (two-way) bar chart."""
    counts = defaultdict(lambda: defaultdict(int))
    for age, gender in participant_qs.values_list("age", "gender"):
        counts[age_bucket_label(age)][gender or "O"] += 1

    labels = age_bucket_order()
    male = [counts[label].get("M", 0) for label in labels]
    female = [counts[label].get("F", 0) for label in labels]
    other = [counts[label].get("O", 0) for label in labels]
    return labels, male, female, other


def monthly_trend(queryset, date_field="date", months_back=12):
    """Returns (labels, values) of record counts per month for the last N
    months, always including empty months so trend lines don't skip gaps."""
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
    rows = queryset.values(field).annotate(v=Count("id")).order_by("-v")
    if limit:
        rows = rows[:limit]
    labels = [r[field] or "Unspecified" for r in rows]
    values = [r["v"] for r in rows]
    return labels, values


def jamat_khana_wise(queryset, field="jamat_khana__name", limit=None):
    rows = queryset.exclude(**{field: None}).values(field).annotate(v=Count("id")).order_by("-v")
    if limit:
        rows = rows[:limit]
    labels = [r[field] or "Unspecified" for r in rows]
    values = [r["v"] for r in rows]
    return labels, values


def portfolio_wise(queryset, portfolio_field="portfolio__name"):
    rows = queryset.values(portfolio_field).annotate(v=Count("id")).order_by("-v")
    labels = [r[portfolio_field] or "Unspecified" for r in rows]
    values = [r["v"] for r in rows]
    return labels, values


def program_wise(queryset, program_field="program__name", limit=12):
    rows = queryset.values(program_field).annotate(v=Count("id")).order_by("-v")[:limit]
    labels = [r[program_field] or "Unspecified" for r in rows]
    values = [r["v"] for r in rows]
    return labels, values


def budget_utilization(cost_total, allocated_total):
    """Returns dict with allocated/utilized/remaining/percent, safe for zero allocation."""
    utilized = cost_total or 0
    allocated = allocated_total or 0
    remaining = max(allocated - utilized, 0)
    return {
        "allocated": allocated,
        "utilized": utilized,
        "remaining": remaining,
        "percent": pct(utilized, allocated) if allocated else None,
    }
