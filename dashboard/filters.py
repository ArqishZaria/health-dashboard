"""
Shared dashboard filter parsing.

Every dashboard (Overview / Activity / Screening / Training / Case) accepts
the same rich set of querystring filters so behaviour is predictable and
"filterable to the smallest unit":

  year, month, day          - cascading date filter (see _compute_date_range)
  region                    - Region id
  local_council              - Local Council id
  jamat_khana                 - Jamatkhana id
  portfolio                  - Portfolio id (Activity / Training)
  program                    - Program id (Activity / Training)
  screening_program           - screening model key (Screening dashboard only)
  status, priority            - Case Management only
  gender                     - M / F / O, wherever a Participant is involved

Date filter cascading rule:
  - nothing selected            -> last 12 months up to today
  - year only                   -> the whole of that year
  - year + month                -> the whole of that month
  - year + month + day          -> that specific day only

The same `DashboardFilters` instance is used to filter the on-screen
analytics AND the CSV export, so what you see is exactly what you download.
Budget Utilization intentionally ignores these filters (it is a fiscal-year
figure, not a date-range one) and is computed from the user's role scope
only.
"""
import calendar
import datetime
from urllib.parse import urlencode

from django.utils import timezone

from core.models import Region, LocalCouncil, JamatKhana, Portfolio, Program

FILTER_KEYS = [
    "year", "month", "day",
    "region", "local_council", "jamat_khana",
    "portfolio", "program",
    "screening_program", "status", "priority", "gender",
]

MONTH_CHOICES = [
    (1, "January"), (2, "February"), (3, "March"), (4, "April"),
    (5, "May"), (6, "June"), (7, "July"), (8, "August"),
    (9, "September"), (10, "October"), (11, "November"), (12, "December"),
]

GENDER_CHOICES = [("M", "Male"), ("F", "Female"), ("O", "Other")]


def year_choices():
    current = timezone.localdate().year
    return list(range(current, current - 8, -1))


class DashboardFilters:
    def __init__(self, request):
        self.raw = {k: request.GET.get(k, "").strip() for k in FILTER_KEYS if request.GET.get(k, "").strip()}
        self.year = self.raw.get("year") or None
        self.month = self.raw.get("month") or None
        self.day = self.raw.get("day") or None
        self.region_id = self.raw.get("region") or None
        self.local_council_id = self.raw.get("local_council") or None
        self.jamat_khana_id = self.raw.get("jamat_khana") or None
        self.portfolio_id = self.raw.get("portfolio") or None
        self.program_id = self.raw.get("program") or None
        self.screening_program = self.raw.get("screening_program") or None
        self.status = self.raw.get("status") or None
        self.priority = self.raw.get("priority") or None
        self.gender = self.raw.get("gender") or None
        self.date_from, self.date_to, self.period_label = self._compute_date_range()

    def _compute_date_range(self):
        today = timezone.localdate()
        if self.year and self.month and self.day:
            try:
                d = datetime.date(int(self.year), int(self.month), int(self.day))
                # Specific-date search can never be in the future, regardless
                # of what the HTML date input's max= attribute allowed
                # client-side (crafted URLs bypass that) - clamp to today.
                if d > today:
                    d = today
                return d, d, f"{d:%d %b %Y}"
            except ValueError:
                pass
        if self.year and self.month:
            try:
                y, m = int(self.year), int(self.month)
                first = datetime.date(y, m, 1)
                last = datetime.date(y, m, calendar.monthrange(y, m)[1])
                if last > today:
                    last = today
                return first, last, f"{calendar.month_name[m]} {y}"
            except ValueError:
                pass
        if self.year:
            try:
                y = int(self.year)
                first = datetime.date(y, 1, 1)
                last = datetime.date(y, 12, 31)
                if last > today:
                    last = today
                return first, last, f"Year {y}"
            except ValueError:
                pass
        # Default: last 12 months up to today
        start_month = today.month - 11
        start_year = today.year
        while start_month <= 0:
            start_month += 12
            start_year -= 1
        start = datetime.date(start_year, start_month, 1)
        return start, today, "Last 12 months"

    @property
    def is_active(self):
        return bool(self.raw)

    def apply(self, qs, date_field="date", region_field="region",
              local_council_field="local_council", jamat_khana_field="jamat_khana",
              portfolio_field=None, program_field=None):
        if self.date_from:
            qs = qs.filter(**{f"{date_field}__gte": self.date_from})
        if self.date_to:
            qs = qs.filter(**{f"{date_field}__lte": self.date_to})
        if self.region_id:
            qs = qs.filter(**{f"{region_field}_id": self.region_id})
        if self.local_council_id and local_council_field:
            qs = qs.filter(**{f"{local_council_field}_id": self.local_council_id})
        if self.jamat_khana_id and jamat_khana_field:
            qs = qs.filter(**{f"{jamat_khana_field}_id": self.jamat_khana_id})
        if portfolio_field and self.portfolio_id:
            qs = qs.filter(**{f"{portfolio_field}_id": self.portfolio_id})
        if program_field and self.program_id:
            qs = qs.filter(**{f"{program_field}_id": self.program_id})
        return qs

    def apply_case_filters(self, qs):
        if self.status:
            qs = qs.filter(current_status=self.status)
        if self.priority:
            qs = qs.filter(priority_level=self.priority)
        return qs

    def apply_gender(self, qs, participant_field="participant"):
        if self.gender:
            qs = qs.filter(**{f"{participant_field}__gender": self.gender})
        return qs

    def querystring(self, exclude=()):
        params = {k: v for k, v in self.raw.items() if k not in exclude}
        return urlencode(params)


def region_choices(user):
    if user.is_superuser or user.is_national:
        return Region.objects.all()
    if user.region_id:
        return Region.objects.filter(id=user.region_id)
    if user.local_council_id:
        return Region.objects.filter(id=user.local_council.region_id)
    return Region.objects.none()


def local_council_choices(user):
    if user.is_superuser or user.is_national:
        return LocalCouncil.objects.select_related("region").all()
    if user.region_id:
        return LocalCouncil.objects.filter(region_id=user.region_id).select_related("region")
    if user.local_council_id:
        return LocalCouncil.objects.filter(id=user.local_council_id).select_related("region")
    return LocalCouncil.objects.none()


def jamat_khana_choices(user):
    if user.is_superuser or user.is_national:
        return JamatKhana.objects.select_related("local_council").all()
    if user.region_id:
        return JamatKhana.objects.filter(local_council__region_id=user.region_id).select_related("local_council")
    if user.local_council_id:
        return JamatKhana.objects.filter(local_council_id=user.local_council_id).select_related("local_council")
    return JamatKhana.objects.none()


def portfolio_choices():
    return Portfolio.objects.all()


def program_choices(portfolio_id=None):
    qs = Program.objects.select_related("portfolio").all()
    if portfolio_id:
        qs = qs.filter(portfolio_id=portfolio_id)
    return qs
