"""
Shared dashboard filter parsing.
See original docstring for behaviour; this version fixes two bugs:
  1. year+month+day was never reached because int(day) raised on an
     ISO date string ("2026-03-05") and was silently swallowed.
  2. region/local_council/jamat_khana/portfolio/program ids were passed
     straight into filter(...) unvalidated, so a non-numeric value in the
     querystring (typed or crafted) raised an uncaught ValueError -> 500.
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


def _safe_int_str(value):
    """Returns the value back as a string only if it's a plain positive
    integer id; otherwise None. Prevents ValueError crashes from
    non-numeric querystring values reaching filter(id=...)."""
    if value and value.isdigit():
        return value
    return None


class DashboardFilters:
    def __init__(self, request):
        self.raw = {k: request.GET.get(k, "").strip() for k in FILTER_KEYS if request.GET.get(k, "").strip()}

        self.region_id = _safe_int_str(self.raw.get("region"))
        self.local_council_id = _safe_int_str(self.raw.get("local_council"))
        self.jamat_khana_id = _safe_int_str(self.raw.get("jamat_khana"))
        self.portfolio_id = _safe_int_str(self.raw.get("portfolio"))
        self.program_id = _safe_int_str(self.raw.get("program"))

        self.screening_program = self.raw.get("screening_program") or None
        self.status = self.raw.get("status") or None
        self.priority = self.raw.get("priority") or None
        self.gender = self.raw.get("gender") if self.raw.get("gender") in ("M", "F", "O") else None

        # --- Date filter parsing -------------------------------------
        # "day" arrives as an ISO date string (YYYY-MM-DD) from the HTML
        # <input type="date">, NOT a day-of-month integer. Parse it as a
        # full date first; year/month are then derived from it so the
        # year+month+day cascade in _compute_date_range still works.
        self.specific_date = None
        raw_day = self.raw.get("day")
        if raw_day:
            try:
                self.specific_date = datetime.date.fromisoformat(raw_day)
            except ValueError:
                self.specific_date = None

        raw_year = _safe_int_str(self.raw.get("year"))
        raw_month = _safe_int_str(self.raw.get("month"))
        if self.specific_date:
            self.year = str(self.specific_date.year)
            self.month = str(self.specific_date.month)
        else:
            self.year = raw_year
            self.month = raw_month if (raw_month and 1 <= int(raw_month) <= 12) else None

        self.date_from, self.date_to, self.period_label = self._compute_date_range()

    def _compute_date_range(self):
        today = timezone.localdate()

        if self.specific_date:
            d = self.specific_date
            if d > today:
                d = today
            return d, d, f"{d:%d %b %Y}"

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

        return None, None, "All Time"

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