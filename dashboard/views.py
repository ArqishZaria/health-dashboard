import csv
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Count, Q, Avg, F, DurationField, ExpressionWrapper
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView, TemplateView

from core.middleware import log_action
from core.models import AuditLog, Region, Portfolio, Program
from core.permissions import RoleRequiredMixin, NationalOnlyMixin

from .forms import (
    UploadForm, ActivityReportForm, CaseRecordForm, CaseFollowUpForm,
    BudgetAllocationForm, TrainingProgramForm,
)
from .importers import process_upload_batch, build_upload_template
from .models import (
    ActivityReport, Participant, TrainingProgram, TrainingAttendance,
    CaseRecord, CaseFollowUp, UploadBatch, BudgetAllocation, SCREENING_MODELS,
)
from .utils import scope_qs, scope_budget_qs
from . import analytics as an
from .filters import (
    DashboardFilters, region_choices, portfolio_choices, program_choices,
    local_council_choices, jamat_khana_choices, year_choices,
    MONTH_CHOICES, GENDER_CHOICES,
)
from .reporting import build_dashboard_pdf

UPLOADER_ROLES = ("NATIONAL", "REGIONAL", "LOCAL", "DATA_ENTRY")


def _pdf_response(pdf_buffer, filename):
    response = HttpResponse(pdf_buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _filters_summary(filters: DashboardFilters, extra_labels=None):
    parts = [filters.period_label]
    if extra_labels:
        parts.extend(extra_labels)
    return ", ".join(parts) if parts else None


def _geo_filter_context(request):
    """Common filter-option context (geography + period) shared by every
    dashboard's filter bar."""
    user = request.user
    return {
        "region_options": region_choices(user),
        "local_council_options": local_council_choices(user),
        "jamat_khana_options": jamat_khana_choices(user),
        "year_options": year_choices(),
        "month_options": MONTH_CHOICES,
        "gender_options": GENDER_CHOICES,
    }


# ===========================================================================
# OVERVIEW - a genuine roll-up of every module below
# ===========================================================================
def _overview_data(request):
    """Shared aggregation for the Overview dashboard and its CSV export.
    Filters (period, region, local council, jamatkhana, portfolio) apply to
    every module's data here; Budget Utilization deliberately ignores
    filters and is computed purely from the user's role scope (it's a
    fiscal-year figure, not a date-range one)."""
    user = request.user
    filters = DashboardFilters(request)

    activities_base = scope_qs(user, ActivityReport.objects.all())
    trainings_base = scope_qs(user, TrainingProgram.objects.all())

    activities = filters.apply(activities_base, date_field="date", region_field="region", portfolio_field="portfolio", program_field="program")
    trainings = filters.apply(trainings_base, date_field="date", region_field="region", portfolio_field="portfolio", program_field="program")
    cases = filters.apply(scope_qs(user, CaseRecord.objects.all()), date_field="referral_date", region_field="region")
    participants = scope_qs(user, Participant.objects.all())
    if filters.region_id:
        participants = participants.filter(region_id=filters.region_id)
    if filters.local_council_id:
        participants = participants.filter(local_council_id=filters.local_council_id)
    if filters.jamat_khana_id:
        participants = participants.filter(jamat_khana_id=filters.jamat_khana_id)
    if filters.gender:
        participants = participants.filter(gender=filters.gender)

    total_screenings = 0
    total_referred = 0
    total_high_risk = 0
    screening_breakdown = []
    screening_region_totals = defaultdict(int)
    screening_local_totals = defaultdict(int)
    screening_jk_totals = defaultdict(int)
    screening_portfolio_totals = defaultdict(int)
    screening_monthly_totals = defaultdict(int)
    screened_participant_ids = set()

    for key, model in SCREENING_MODELS.items():
        qs = scope_qs(user, model.objects.all())
        qs = filters.apply(qs, date_field="screening_date", region_field="region", portfolio_field=None, program_field=None)
        qs = filters.apply_gender(qs)
        if filters.portfolio_id:
            qs = qs.filter(program__portfolio_id=filters.portfolio_id)
        count = qs.count()
        referred = qs.filter(referred=True).count()
        high_risk = qs.filter(risk_category="HIGH").count()
        total_screenings += count
        total_referred += referred
        total_high_risk += high_risk
        screening_breakdown.append({
            "label": model._meta.verbose_name, "key": key, "count": count,
            "referred": referred, "referral_rate": an.pct(referred, count),
        })
        screened_participant_ids.update(qs.values_list("participant_id", flat=True))
        for region_name, c in qs.values_list("region__name").annotate(c=Count("id")):
            screening_region_totals[region_name or "Unspecified"] += c
        for lc_name, c in qs.values_list("local_council__name").annotate(c=Count("id")):
            screening_local_totals[lc_name or "Unspecified"] += c
        for jk_name, c in qs.exclude(jamat_khana__isnull=True).values_list("jamat_khana__name").annotate(c=Count("id")):
            screening_jk_totals[jk_name or "Unspecified"] += c
        for portfolio_name, c in qs.values_list("program__portfolio__name").annotate(c=Count("id")):
            screening_portfolio_totals[portfolio_name or "Unspecified"] += c
        labels, values = an.monthly_trend(qs, date_field="screening_date")
        for label, v in zip(labels, values):
            screening_monthly_totals[label] += v

    # Combined region-wise analysis
    region_combo = defaultdict(lambda: {"activities": 0, "screenings": 0, "trainings": 0, "cases": 0})
    for row in activities.values("region__name").annotate(c=Count("id")):
        region_combo[row["region__name"] or "Unspecified"]["activities"] = row["c"]
    for region_name, c in screening_region_totals.items():
        region_combo[region_name]["screenings"] = c
    for row in trainings.values("region__name").annotate(c=Count("id")):
        region_combo[row["region__name"] or "Unspecified"]["trainings"] = row["c"]
    for row in cases.values("region__name").annotate(c=Count("id")):
        region_combo[row["region__name"] or "Unspecified"]["cases"] = row["c"]
    region_combo_rows = [
        {"region": r, **vals, "total": sum(vals.values())}
        for r, vals in sorted(region_combo.items(), key=lambda kv: -sum(kv[1].values()))
    ]

    # Combined local-council-wise analysis (top 5)
    local_combo = defaultdict(lambda: {"activities": 0, "screenings": 0, "trainings": 0, "cases": 0})
    for row in activities.values("local_council__name").annotate(c=Count("id")):
        local_combo[row["local_council__name"] or "Unspecified"]["activities"] = row["c"]
    for lc_name, c in screening_local_totals.items():
        local_combo[lc_name]["screenings"] = c
    for row in trainings.values("local_council__name").annotate(c=Count("id")):
        local_combo[row["local_council__name"] or "Unspecified"]["trainings"] = row["c"]
    for row in cases.values("local_council__name").annotate(c=Count("id")):
        local_combo[row["local_council__name"] or "Unspecified"]["cases"] = row["c"]
    local_combo_rows_all = [
        {"local_council": lc, **vals, "total": sum(vals.values())}
        for lc, vals in sorted(local_combo.items(), key=lambda kv: -sum(kv[1].values()))
    ]
    local_combo_rows = local_combo_rows_all[:5]

    # Combined jamatkhana-wise analysis (top 5)
    jk_combo = defaultdict(lambda: {"activities": 0, "screenings": 0, "trainings": 0, "cases": 0})
    for row in activities.exclude(jamat_khana__isnull=True).values("jamat_khana__name").annotate(c=Count("id")):
        jk_combo[row["jamat_khana__name"] or "Unspecified"]["activities"] = row["c"]
    for jk_name, c in screening_jk_totals.items():
        jk_combo[jk_name]["screenings"] = c
    for row in trainings.exclude(jamat_khana__isnull=True).values("jamat_khana__name").annotate(c=Count("id")):
        jk_combo[row["jamat_khana__name"] or "Unspecified"]["trainings"] = row["c"]
    for row in cases.exclude(jamat_khana__isnull=True).values("jamat_khana__name").annotate(c=Count("id")):
        jk_combo[row["jamat_khana__name"] or "Unspecified"]["cases"] = row["c"]
    jk_combo_rows_all = [
        {"jamat_khana": jk, **vals, "total": sum(vals.values())}
        for jk, vals in sorted(jk_combo.items(), key=lambda kv: -sum(kv[1].values()))
    ]
    jk_combo_rows = jk_combo_rows_all[:5]

    # Combined portfolio-wise analysis
    portfolio_combo = defaultdict(lambda: {"activities": 0, "trainings": 0, "screenings": 0})
    for row in activities.values("portfolio__name").annotate(c=Count("id")):
        portfolio_combo[row["portfolio__name"] or "Unspecified"]["activities"] = row["c"]
    for row in trainings.values("portfolio__name").annotate(c=Count("id")):
        portfolio_combo[row["portfolio__name"] or "Unspecified"]["trainings"] = row["c"]
    for portfolio_name, c in screening_portfolio_totals.items():
        portfolio_combo[portfolio_name]["screenings"] = c
    portfolio_combo_rows = [
        {"portfolio": p, **vals, "total": sum(vals.values())}
        for p, vals in sorted(portfolio_combo.items(), key=lambda kv: -sum(kv[1].values()))
    ]

    age_gender_qs = participants.filter(id__in=screened_participant_ids)
    age_labels, male_series, female_series, other_series = an.age_gender_breakdown(age_gender_qs)

    act_labels, act_values = an.monthly_trend(activities, date_field="date")
    train_labels, train_values = an.monthly_trend(trainings, date_field="date")
    case_labels, case_values = an.monthly_trend(cases, date_field="referral_date")
    screening_month_values = [screening_monthly_totals.get(label, 0) for label in act_labels]

    year_labels, year_activity_values = an.yearly_trend(activities, date_field="date")
    _, year_training_values = an.yearly_trend(trainings, date_field="date")

    # Budget utilization - scope only, NOT filtered by the dashboard filters
    allocations = scope_budget_qs(user, BudgetAllocation.objects.all())
    total_allocated = allocations.aggregate(s=Sum("allocated_amount"))["s"] or 0
    total_cost = (activities_base.aggregate(s=Sum("cost"))["s"] or 0) + (trainings_base.aggregate(s=Sum("cost"))["s"] or 0)
    budget = an.budget_utilization(total_cost, total_allocated)

    cases_closed = cases.filter(current_status="CLOSED").count()
    cases_total = cases.count()
    total_activities_count = activities.count()
    total_beneficiaries_sum = activities.aggregate(s=Sum("number_of_beneficiaries"))["s"] or 0
    avg_beneficiaries_per_activity = round(total_beneficiaries_sum / total_activities_count, 1) if total_activities_count else 0

    screening_breakdown = sorted(screening_breakdown, key=lambda r: -r["count"])

    return {
        "filters": filters,
        "total_activities": total_activities_count,
        "total_beneficiaries": total_beneficiaries_sum,
        "avg_beneficiaries_per_activity": avg_beneficiaries_per_activity,
        "total_screenings": total_screenings,
        "total_referrals": total_referred,
        "total_high_risk": total_high_risk,
        "overall_referral_rate": an.pct(total_referred, total_screenings),
        "total_trainings": trainings.count(),
        "total_training_participants": trainings.aggregate(s=Sum("number_of_participants"))["s"] or 0,
        "cases_total": cases_total,
        "cases_open": cases.exclude(current_status="CLOSED").count(),
        "cases_closed": cases_closed,
        "case_closure_rate": an.pct(cases_closed, cases_total),
        "screening_breakdown": screening_breakdown,
        "budget": budget,
        "region_combo_rows": region_combo_rows,
        "local_combo_rows": local_combo_rows,
        "jk_combo_rows": jk_combo_rows,
        "portfolio_combo_rows": portfolio_combo_rows,
        "age_labels": age_labels, "male_series": male_series, "female_series": female_series, "other_series": other_series,
        "combo_month_labels": act_labels, "combo_activity_values": act_values,
        "combo_training_values": train_values, "combo_case_values": case_values,
        "combo_screening_values": screening_month_values,
        "year_labels": year_labels, "year_activity_values": year_activity_values, "year_training_values": year_training_values,
        "region_labels": [r["region"] for r in region_combo_rows[:10]],
        "region_values": [r["total"] for r in region_combo_rows[:10]],
        "screening_labels": [s["label"] for s in screening_breakdown],
        "screening_values": [s["count"] for s in screening_breakdown],
    }


class OverviewDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/overview.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        data = _overview_data(self.request)
        for key in ("age_labels", "male_series", "female_series", "other_series", "combo_month_labels",
                    "combo_activity_values", "combo_training_values", "combo_case_values", "combo_screening_values",
                    "year_labels", "year_activity_values", "year_training_values", "region_labels", "region_values",
                    "screening_labels", "screening_values"):
            data[key] = an.chart_json(data[key])
        ctx.update(data)
        ctx.update(_geo_filter_context(self.request))
        ctx["portfolio_options"] = portfolio_choices()
        ctx["export_qs"] = data["filters"].querystring()
        return ctx


class ExportOverviewSummaryCSVView(LoginRequiredMixin, View):
    """Consolidated region-wise summary across every module, respecting the
    same filters shown on the Overview dashboard."""
    def get(self, request):
        data = _overview_data(request)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="overview_summary_{timezone.now():%Y%m%d}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Region", "Activities", "Screenings", "Trainings", "Cases", "Total Records"])
        for r in data["region_combo_rows"]:
            writer.writerow([r["region"], r["activities"], r["screenings"], r["trainings"], r["cases"], r["total"]])
        writer.writerow([])
        writer.writerow(["Top 5 Local Councils", "Activities", "Screenings", "Trainings", "Cases", "Total Records"])
        for r in data["local_combo_rows"]:
            writer.writerow([r["local_council"], r["activities"], r["screenings"], r["trainings"], r["cases"], r["total"]])
        writer.writerow([])
        writer.writerow(["Top 5 Jamatkhanas", "Activities", "Screenings", "Trainings", "Cases", "Total Records"])
        for r in data["jk_combo_rows"]:
            writer.writerow([r["jamat_khana"], r["activities"], r["screenings"], r["trainings"], r["cases"], r["total"]])
        return response


class ExportOverviewPDFView(LoginRequiredMixin, View):
    """Retained for backward compatibility (linkable directly); the UI now
    only surfaces the Print action per dashboard, per the latest design."""
    def get(self, request):
        data = _overview_data(request)
        kpis = [
            ("Total Beneficiaries", data["total_beneficiaries"]),
            ("Total Activities", data["total_activities"]),
            ("Total Screenings", data["total_screenings"]),
            ("Total Referrals", f'{data["total_referrals"]} ({data["overall_referral_rate"]}%)'),
            ("High-Risk Screenings", data["total_high_risk"]),
            ("Total Trainings", data["total_trainings"]),
            ("Training Participants", data["total_training_participants"]),
            ("Cases Under Follow-up", data["cases_open"]),
            ("Cases Closed", f'{data["cases_closed"]} ({data["case_closure_rate"]}%)'),
        ]
        charts = [
            {"type": "line", "title": "12-Month Trend - Activities", "labels": data["combo_month_labels"], "values": data["combo_activity_values"]},
            {"type": "bar", "title": "Top Regions by Total Activity", "labels": [r["region"] for r in data["region_combo_rows"][:10]], "values": [r["total"] for r in data["region_combo_rows"][:10]]},
            {"type": "pie", "title": "Screenings by Program", "labels": data["screening_labels"], "values": data["screening_values"]},
        ]
        tables = [
            {"title": "Region-wise Breakdown", "headers": ["Region", "Activities", "Screenings", "Trainings", "Cases", "Total"],
             "rows": [[r["region"], r["activities"], r["screenings"], r["trainings"], r["cases"], r["total"]] for r in data["region_combo_rows"]]},
            {"title": "Top 5 Local Councils", "headers": ["Local Council", "Activities", "Screenings", "Trainings", "Cases", "Total"],
             "rows": [[r["local_council"], r["activities"], r["screenings"], r["trainings"], r["cases"], r["total"]] for r in data["local_combo_rows"]]},
            {"title": "Top 5 Jamatkhanas", "headers": ["Jamatkhana", "Activities", "Screenings", "Trainings", "Cases", "Total"],
             "rows": [[r["jamat_khana"], r["activities"], r["screenings"], r["trainings"], r["cases"], r["total"]] for r in data["jk_combo_rows"]]},
            {"title": "Portfolio-wise Breakdown", "headers": ["Portfolio", "Activities", "Trainings", "Screenings", "Total"],
             "rows": [[p["portfolio"], p["activities"], p["trainings"], p["screenings"], p["total"]] for p in data["portfolio_combo_rows"]]},
            {"title": "Screening Programs Summary", "headers": ["Program", "Total Screened", "Referred", "Referral Rate"],
             "rows": [[s["label"], s["count"], s["referred"], f'{s["referral_rate"]}%'] for s in data["screening_breakdown"]]},
        ]
        pdf = build_dashboard_pdf(
            "Overview Dashboard Report", "Integrated Health Programs Data Management System",
            kpis, charts, tables, filters_summary=_filters_summary(data["filters"]),
        )
        return _pdf_response(pdf, f"overview_dashboard_{timezone.now():%Y%m%d}.pdf")


# ===========================================================================
# ACTIVITY REPORTING
# ===========================================================================
class ActivityReportListView(LoginRequiredMixin, ListView):
    model = ActivityReport
    template_name = "dashboard/activity_list.html"
    context_object_name = "activities"
    paginate_by = 25

    def get_queryset(self):
        qs = scope_qs(self.request.user, ActivityReport.objects.select_related("region", "portfolio", "program"))
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(Q(name_of_activity__icontains=q) | Q(venue__icontains=q))
        return qs.order_by("-date")


def _activity_data(request):
    user = request.user
    filters = DashboardFilters(request)
    base_qs = scope_qs(user, ActivityReport.objects.all())
    qs = filters.apply(base_qs, date_field="date", region_field="region", portfolio_field="portfolio", program_field="program")

    program_labels, program_values = an.program_wise(qs)
    portfolio_labels, portfolio_values = an.portfolio_wise(qs)
    region_labels, region_values = an.region_wise(qs)
    local_labels, local_values = an.local_council_wise(qs, limit=5)
    jk_labels, jk_values = an.jamat_khana_wise(qs, limit=5)
    month_labels, month_values = an.monthly_trend(qs, date_field="date")
    year_labels, year_values = an.yearly_trend(qs, date_field="date")

    allocations = scope_budget_qs(
        user, BudgetAllocation.objects.filter(portfolio_id__in=base_qs.values_list("portfolio_id", flat=True).distinct())
    )
    total_allocated = allocations.aggregate(s=Sum("allocated_amount"))["s"] or 0
    total_cost_unfiltered = base_qs.aggregate(s=Sum("cost"))["s"] or 0
    budget = an.budget_utilization(total_cost_unfiltered, total_allocated)

    total = qs.count()
    beneficiaries = qs.aggregate(s=Sum("number_of_beneficiaries"))["s"] or 0

    return {
        "filters": filters,
        "total": total,
        "beneficiaries": beneficiaries,
        "avg_beneficiaries": round(beneficiaries / total, 1) if total else 0,
        "budget": budget,
        "program_labels": program_labels, "program_values": program_values,
        "portfolio_labels": portfolio_labels, "portfolio_values": portfolio_values,
        "region_labels": region_labels, "region_values": region_values,
        "local_labels": local_labels, "local_values": local_values,
        "jk_labels": jk_labels, "jk_values": jk_values,
        "month_labels": month_labels, "month_values": month_values,
        "year_labels": year_labels, "year_values": year_values,
        "records": qs.select_related("region", "portfolio", "program").order_by("-date"),
    }


class ActivityReportDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/activity_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        data = _activity_data(self.request)
        for key in ("program_labels", "program_values", "portfolio_labels", "portfolio_values",
                    "region_labels", "region_values", "local_labels", "local_values", "jk_labels", "jk_values",
                    "month_labels", "month_values", "year_labels", "year_values"):
            ctx[key] = an.chart_json(data[key])
        ctx.update({k: v for k, v in data.items() if k not in ctx})
        ctx.update(_geo_filter_context(self.request))
        ctx["portfolio_options"] = portfolio_choices()
        ctx["program_options"] = program_choices()
        ctx["export_qs"] = data["filters"].querystring()
        return ctx


class ActivityReportCreateView(LoginRequiredMixin, CreateView):
    """Backend retained for direct-URL/admin use; the UI no longer links to
    it (bulk upload + edit is the supported data-entry workflow)."""
    model = ActivityReport
    form_class = ActivityReportForm
    template_name = "dashboard/activity_form.html"
    success_url = reverse_lazy("dashboard:activity_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        log_action(self.request, AuditLog.Action.CREATE, "ActivityReport", self.object.pk, str(self.object))
        messages.success(self.request, "Activity report saved.")
        return response


class ActivityReportUpdateView(LoginRequiredMixin, UpdateView):
    model = ActivityReport
    form_class = ActivityReportForm
    template_name = "dashboard/activity_form.html"
    success_url = reverse_lazy("dashboard:activity_list")

    def get_queryset(self):
        return scope_qs(self.request.user, ActivityReport.objects.all())

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request, AuditLog.Action.UPDATE, "ActivityReport", self.object.pk, str(self.object))
        return response


class ActivityReportDeleteView(LoginRequiredMixin, DeleteView):
    model = ActivityReport
    template_name = "dashboard/confirm_delete.html"
    success_url = reverse_lazy("dashboard:activity_list")

    def get_queryset(self):
        return scope_qs(self.request.user, ActivityReport.objects.all())


class ExportActivitiesCSVView(LoginRequiredMixin, View):
    def get(self, request):
        data = _activity_data(request)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="activity_reports_{timezone.now():%Y%m%d}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Date", "Region", "Local Council", "Venue", "Portfolio", "Program", "Activity", "Beneficiaries", "Cost", "Facilitator"])
        for a in data["records"]:
            writer.writerow([a.date, a.region.name, a.local_council.name, a.venue, a.portfolio.name, a.program.name, a.name_of_activity, a.number_of_beneficiaries, a.cost, a.facilitator_trainer])
        return response


class ExportActivityPDFView(LoginRequiredMixin, View):
    def get(self, request):
        data = _activity_data(request)
        kpis = [
            ("Total Activities", data["total"]),
            ("Total Beneficiaries", data["beneficiaries"]),
            ("Avg. Beneficiaries / Activity", data["avg_beneficiaries"]),
        ]
        charts = [
            {"type": "line", "title": "Monthly Trend", "labels": data["month_labels"], "values": data["month_values"]},
            {"type": "bar", "title": "Yearly Trend", "labels": data["year_labels"], "values": data["year_values"]},
            {"type": "pie", "title": "Portfolio-wise Breakdown", "labels": data["portfolio_labels"], "values": data["portfolio_values"]},
            {"type": "barh", "title": "Top Programs", "labels": data["program_labels"], "values": data["program_values"]},
        ]
        tables = [
            {"title": "Region-wise Analysis", "headers": ["Region", "Activities"], "rows": list(zip(data["region_labels"], data["region_values"]))},
            {"title": "Top 5 Local Councils", "headers": ["Local Council", "Activities"], "rows": list(zip(data["local_labels"], data["local_values"]))},
            {"title": "Top 5 Jamatkhanas", "headers": ["Jamatkhana", "Activities"], "rows": list(zip(data["jk_labels"], data["jk_values"]))},
        ]
        pdf = build_dashboard_pdf(
            "Activity Reporting Dashboard", "Integrated Health Programs Data Management System",
            kpis, charts, tables, filters_summary=_filters_summary(data["filters"]),
        )
        return _pdf_response(pdf, f"activity_dashboard_{timezone.now():%Y%m%d}.pdf")


# ===========================================================================
# HEALTH SCREENING PROGRAMS
# ===========================================================================
def _screening_data(request):
    user = request.user
    filters = DashboardFilters(request)
    models_to_scan = SCREENING_MODELS
    if filters.screening_program and filters.screening_program in SCREENING_MODELS:
        models_to_scan = {filters.screening_program: SCREENING_MODELS[filters.screening_program]}

    rows = []
    total = referred_total = high_risk_total = 0
    region_totals = defaultdict(int)
    local_totals = defaultdict(int)
    jk_totals = defaultdict(int)
    monthly_totals = defaultdict(int)
    yearly_totals = defaultdict(int)
    all_participant_ids = set()
    month_label_order = []

    for key, model in models_to_scan.items():
        qs = scope_qs(user, model.objects.all())
        qs = filters.apply(qs, date_field="screening_date", region_field="region")
        qs = filters.apply_gender(qs)
        count = qs.count()
        referred = qs.filter(referred=True).count()
        high_risk = qs.filter(risk_category="HIGH").count()
        total += count
        referred_total += referred
        high_risk_total += high_risk
        rows.append({
            "key": key, "label": model._meta.verbose_name, "count": count,
            "referred": referred, "high_risk": high_risk, "referral_rate": an.pct(referred, count),
        })
        all_participant_ids.update(qs.values_list("participant_id", flat=True))
        for region_name, c in qs.values_list("region__name").annotate(c=Count("id")):
            region_totals[region_name or "Unspecified"] += c
        for lc_name, c in qs.values_list("local_council__name").annotate(c=Count("id")):
            local_totals[lc_name or "Unspecified"] += c
        for jk_name, c in qs.exclude(jamat_khana__isnull=True).values_list("jamat_khana__name").annotate(c=Count("id")):
            jk_totals[jk_name or "Unspecified"] += c
        m_labels, m_values = an.monthly_trend(qs, date_field="screening_date")
        if not month_label_order:
            month_label_order = m_labels
        for label, v in zip(m_labels, m_values):
            monthly_totals[label] += v
        y_labels, y_values = an.yearly_trend(qs, date_field="screening_date")
        for label, v in zip(y_labels, y_values):
            yearly_totals[label] += v

    participants = scope_qs(user, Participant.objects.filter(id__in=all_participant_ids))
    age_labels, male_series, female_series, other_series = an.age_gender_breakdown(participants)

    gender_counts = defaultdict(int)
    for g, c in participants.values_list("gender").annotate(c=Count("id")):
        gender_counts[g] += c
    gender_display = {"M": "Male", "F": "Female", "O": "Other"}

    rows = sorted(rows, key=lambda r: -r["count"])
    month_labels = month_label_order or an.monthly_trend(Participant.objects.none(), date_field="created_at")[0]
    month_values = [monthly_totals.get(l, 0) for l in month_labels]
    year_labels_sorted = sorted(yearly_totals.keys())
    year_values = [yearly_totals[y] for y in year_labels_sorted]

    local_sorted = sorted(local_totals.items(), key=lambda kv: -kv[1])[:5]
    jk_sorted = sorted(jk_totals.items(), key=lambda kv: -kv[1])[:5]

    return {
        "filters": filters,
        "rows": rows,
        "total": total,
        "referred_total": referred_total,
        "high_risk_total": high_risk_total,
        "overall_referral_rate": an.pct(referred_total, total),
        "labels": [r["label"] for r in rows],
        "values": [r["count"] for r in rows],
        "gender_labels": [gender_display.get(g, "Other") for g in gender_counts.keys()],
        "gender_values": list(gender_counts.values()),
        "age_labels": age_labels, "male_series": male_series, "female_series": female_series, "other_series": other_series,
        "region_labels": list(region_totals.keys()), "region_values": list(region_totals.values()),
        "local_labels": [x[0] for x in local_sorted], "local_values": [x[1] for x in local_sorted],
        "jk_labels": [x[0] for x in jk_sorted], "jk_values": [x[1] for x in jk_sorted],
        "month_labels": month_labels, "month_values": month_values,
        "year_labels": year_labels_sorted, "year_values": year_values,
    }


class ScreeningDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/screening_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        data = _screening_data(self.request)
        for key in ("labels", "values", "gender_labels", "gender_values", "age_labels", "male_series",
                    "female_series", "other_series", "region_labels", "region_values",
                    "local_labels", "local_values", "jk_labels", "jk_values", "month_labels",
                    "month_values", "year_labels", "year_values"):
            ctx[key] = an.chart_json(data[key])
        ctx.update({k: v for k, v in data.items() if k not in ctx})
        ctx.update(_geo_filter_context(self.request))
        ctx["screening_options"] = [(k, m._meta.verbose_name) for k, m in SCREENING_MODELS.items()]
        ctx["export_qs"] = data["filters"].querystring()
        return ctx


class ScreeningRecordListView(LoginRequiredMixin, ListView):
    template_name = "dashboard/screening_list.html"
    context_object_name = "records"
    paginate_by = 25

    def dispatch(self, request, *args, **kwargs):
        self.model_key = kwargs["model_key"]
        self.model = SCREENING_MODELS.get(self.model_key)
        if self.model is None:
            messages.error(request, "Unknown screening form type.")
            return redirect("dashboard:screening_dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        qs = scope_qs(self.request.user, self.model.objects.select_related("participant", "region", "local_council"))
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(Q(participant__full_name__icontains=q) | Q(participant__cnic__icontains=q))
        return qs.order_by("-screening_date")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["model_key"] = self.model_key
        ctx["model_label"] = self.model._meta.verbose_name
        return ctx


class ParticipantListView(LoginRequiredMixin, ListView):
    model = Participant
    template_name = "dashboard/participant_list.html"
    context_object_name = "participants"
    paginate_by = 25

    def get_queryset(self):
        qs = scope_qs(self.request.user, Participant.objects.all())
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(cnic__icontains=q) | Q(participant_uid__icontains=q))
        return qs


class ParticipantDetailView(LoginRequiredMixin, DetailView):
    model = Participant
    template_name = "dashboard/participant_detail.html"
    context_object_name = "participant"

    def get_queryset(self):
        return scope_qs(self.request.user, Participant.objects.all())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = self.object
        screenings = []
        for key, model in SCREENING_MODELS.items():
            records = model.objects.filter(participant=p)
            if records.exists():
                screenings.append({"label": model._meta.verbose_name, "key": key, "records": records})
        ctx["screenings"] = screenings
        ctx["cases"] = p.cases.all()
        return ctx


class ExportScreeningCSVView(LoginRequiredMixin, View):
    """Exports the currently filtered rows for ONE screening type (from the
    record list page); use ExportScreeningDashboardCSVView for the aggregate
    dashboard summary export."""
    def get(self, request, model_key):
        model = SCREENING_MODELS.get(model_key)
        if model is None:
            messages.error(request, "Unknown screening form type.")
            return redirect("dashboard:screening_dashboard")
        filters = DashboardFilters(request)
        qs = scope_qs(request.user, model.objects.select_related("participant", "region", "local_council"))
        qs = filters.apply(qs, date_field="screening_date", region_field="region").order_by("-screening_date")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{model_key}_export_{timezone.now():%Y%m%d}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Participant", "CNIC", "Gender", "Age", "Region", "Local Council", "Date", "Referred", "Risk Category", "Remarks"])
        for r in qs:
            writer.writerow([
                r.participant.full_name, r.participant.cnic, r.participant.get_gender_display(),
                r.participant.age, r.region.name, r.local_council.name, r.screening_date,
                "Yes" if r.referred else "No", r.get_risk_category_display(), r.remarks,
            ])
        return response


class ExportScreeningDashboardCSVView(LoginRequiredMixin, View):
    """Aggregate summary export (one row per screening program) for the
    Screening dashboard, respecting the same filters shown on screen."""
    def get(self, request):
        data = _screening_data(request)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="screening_summary_{timezone.now():%Y%m%d}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Program", "Total Screened", "Referred", "Referral Rate (%)", "High Risk"])
        for r in data["rows"]:
            writer.writerow([r["label"], r["count"], r["referred"], r["referral_rate"], r["high_risk"]])
        return response


class ExportScreeningPDFView(LoginRequiredMixin, View):
    def get(self, request):
        data = _screening_data(request)
        kpis = [
            ("Total Screened", data["total"]),
            ("Total Referred", f'{data["referred_total"]} ({data["overall_referral_rate"]}%)'),
            ("High-Risk Cases", data["high_risk_total"]),
            ("Screening Programs Included", len(data["rows"])),
        ]
        charts = [
            {"type": "bar", "title": "Screenings by Program", "labels": data["labels"], "values": data["values"]},
            {"type": "line", "title": "Monthly Trend", "labels": data["month_labels"], "values": data["month_values"]},
            {"type": "pie", "title": "Region-wise Screenings", "labels": data["region_labels"], "values": data["region_values"]},
            {"type": "bar", "title": "Age Group Distribution (All Genders)", "labels": data["age_labels"],
             "values": [m + f + o for m, f, o in zip(data["male_series"], data["female_series"], data["other_series"])]},
        ]
        tables = [
            {"title": "Screening Programs — Detail", "headers": ["Program", "Total", "Referred", "Referral Rate", "High Risk"],
             "rows": [[r["label"], r["count"], r["referred"], f'{r["referral_rate"]}%', r["high_risk"]] for r in data["rows"]]},
            {"title": "Top 5 Local Councils", "headers": ["Local Council", "Screenings"], "rows": list(zip(data["local_labels"], data["local_values"]))},
            {"title": "Top 5 Jamatkhanas", "headers": ["Jamatkhana", "Screenings"], "rows": list(zip(data["jk_labels"], data["jk_values"]))},
        ]
        pdf = build_dashboard_pdf(
            "Health Screening Programs Dashboard", "Integrated Health Programs Data Management System",
            kpis, charts, tables, filters_summary=_filters_summary(data["filters"]),
        )
        return _pdf_response(pdf, f"screening_dashboard_{timezone.now():%Y%m%d}.pdf")


# ===========================================================================
# TRAINING & CAPACITY BUILDING
# ===========================================================================
def _training_data(request):
    user = request.user
    filters = DashboardFilters(request)
    base_qs = scope_qs(user, TrainingProgram.objects.all())
    qs = filters.apply(base_qs, date_field="date", region_field="region", portfolio_field="portfolio", program_field="program")

    portfolio_labels, portfolio_values = an.portfolio_wise(qs)
    program_labels, program_values = an.program_wise(qs)
    region_labels, region_values = an.region_wise(qs)
    local_labels, local_values = an.local_council_wise(qs, limit=5)
    jk_labels, jk_values = an.jamat_khana_wise(qs, limit=5)
    month_labels, month_values = an.monthly_trend(qs, date_field="date")
    year_labels, year_values = an.yearly_trend(qs, date_field="date")

    attendance_qs = TrainingAttendance.objects.filter(training__in=qs)
    by_status = attendance_qs.values("attendance_status").annotate(c=Count("id"))
    status_display = dict(TrainingAttendance.ATTENDANCE_CHOICES)
    attendance_labels = [status_display.get(r["attendance_status"], r["attendance_status"]) for r in by_status]
    attendance_values = [r["c"] for r in by_status]
    total_attendees = attendance_qs.count()
    present_count = attendance_qs.filter(attendance_status="PRESENT").count()

    allocations = scope_budget_qs(
        user, BudgetAllocation.objects.filter(portfolio_id__in=base_qs.values_list("portfolio_id", flat=True).distinct())
    )
    total_allocated = allocations.aggregate(s=Sum("allocated_amount"))["s"] or 0
    total_cost_unfiltered = base_qs.aggregate(s=Sum("cost"))["s"] or 0
    budget = an.budget_utilization(total_cost_unfiltered, total_allocated)

    total_trainings = qs.count()
    total_participants = qs.aggregate(s=Sum("number_of_participants"))["s"] or 0
    top_trainers = list(qs.values("trainer_name").annotate(c=Count("id")).order_by("-c")[:8])

    return {
        "filters": filters,
        "total_trainings": total_trainings,
        "total_participants": total_participants,
        "avg_participants": round(total_participants / total_trainings, 1) if total_trainings else 0,
        "avg_duration": round(qs.aggregate(a=Avg("duration_hours"))["a"] or 0, 1),
        "attendance_rate": an.pct(present_count, total_attendees),
        "budget": budget,
        "top_trainers": top_trainers,
        "portfolio_labels": portfolio_labels, "portfolio_values": portfolio_values,
        "program_labels": program_labels, "program_values": program_values,
        "region_labels": region_labels, "region_values": region_values,
        "local_labels": local_labels, "local_values": local_values,
        "jk_labels": jk_labels, "jk_values": jk_values,
        "month_labels": month_labels, "month_values": month_values,
        "year_labels": year_labels, "year_values": year_values,
        "attendance_labels": attendance_labels, "attendance_values": attendance_values,
        "records": qs.select_related("region", "portfolio", "program").order_by("-date"),
    }


class TrainingDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/training_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        data = _training_data(self.request)
        for key in ("portfolio_labels", "portfolio_values", "program_labels", "program_values", "region_labels",
                    "region_values", "local_labels", "local_values", "jk_labels", "jk_values",
                    "month_labels", "month_values", "year_labels", "year_values",
                    "attendance_labels", "attendance_values"):
            ctx[key] = an.chart_json(data[key])
        ctx.update({k: v for k, v in data.items() if k not in ctx})
        ctx.update(_geo_filter_context(self.request))
        ctx["portfolio_options"] = portfolio_choices()
        ctx["program_options"] = program_choices()
        ctx["export_qs"] = data["filters"].querystring()
        return ctx


class TrainingListView(LoginRequiredMixin, ListView):
    model = TrainingProgram
    template_name = "dashboard/training_list.html"
    context_object_name = "trainings"
    paginate_by = 25

    def get_queryset(self):
        return scope_qs(self.request.user, TrainingProgram.objects.select_related("portfolio", "program", "region")).order_by("-date")


class TrainingCreateView(LoginRequiredMixin, CreateView):
    """Backend retained for direct-URL/admin use; not linked from the UI."""
    model = TrainingProgram
    form_class = TrainingProgramForm
    template_name = "dashboard/training_form.html"
    success_url = reverse_lazy("dashboard:training_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        log_action(self.request, AuditLog.Action.CREATE, "TrainingProgram", self.object.pk, str(self.object))
        messages.success(self.request, "Training program saved.")
        return response


class TrainingUpdateView(LoginRequiredMixin, UpdateView):
    model = TrainingProgram
    form_class = TrainingProgramForm
    template_name = "dashboard/training_form.html"

    def get_queryset(self):
        return scope_qs(self.request.user, TrainingProgram.objects.all())

    def get_success_url(self):
        return reverse("dashboard:training_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request, AuditLog.Action.UPDATE, "TrainingProgram", self.object.pk, str(self.object))
        return response


class TrainingDetailView(LoginRequiredMixin, DetailView):
    model = TrainingProgram
    template_name = "dashboard/training_detail.html"
    context_object_name = "training"

    def get_queryset(self):
        return scope_qs(self.request.user, TrainingProgram.objects.all())


class ExportTrainingCSVView(LoginRequiredMixin, View):
    def get(self, request):
        data = _training_data(request)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="training_programs_{timezone.now():%Y%m%d}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Date", "Title", "Region", "Portfolio", "Program", "Trainer", "Duration (hrs)", "Participants", "Cost"])
        for t in data["records"]:
            writer.writerow([t.date, t.title, t.region.name, t.portfolio.name, t.program.name, t.trainer_name, t.duration_hours, t.number_of_participants, t.cost])
        return response


class ExportTrainingPDFView(LoginRequiredMixin, View):
    def get(self, request):
        data = _training_data(request)
        kpis = [
            ("Total Trainings", data["total_trainings"]),
            ("Total Participants", data["total_participants"]),
            ("Avg. Participants / Training", data["avg_participants"]),
            ("Avg. Duration (hrs)", data["avg_duration"]),
            ("Attendance Rate", f'{data["attendance_rate"]}%'),
        ]
        charts = [
            {"type": "line", "title": "Monthly Trend", "labels": data["month_labels"], "values": data["month_values"]},
            {"type": "bar", "title": "Yearly Trend", "labels": data["year_labels"], "values": data["year_values"]},
            {"type": "pie", "title": "Attendance Status Breakdown", "labels": data["attendance_labels"], "values": data["attendance_values"]},
            {"type": "barh", "title": "Top Programs", "labels": data["program_labels"], "values": data["program_values"]},
        ]
        tables = [
            {"title": "Region-wise Analysis", "headers": ["Region", "Trainings"], "rows": list(zip(data["region_labels"], data["region_values"]))},
            {"title": "Top Trainers", "headers": ["Trainer", "Sessions"], "rows": [[t["trainer_name"] or "Unspecified", t["c"]] for t in data["top_trainers"]]},
        ]
        pdf = build_dashboard_pdf(
            "Training & Capacity Building Dashboard", "Integrated Health Programs Data Management System",
            kpis, charts, tables, filters_summary=_filters_summary(data["filters"]),
        )
        return _pdf_response(pdf, f"training_dashboard_{timezone.now():%Y%m%d}.pdf")


# ===========================================================================
# CASE MANAGEMENT AND REFERRALS
# ===========================================================================
def _case_data(request):
    user = request.user
    filters = DashboardFilters(request)
    qs = filters.apply(scope_qs(user, CaseRecord.objects.all()), date_field="referral_date", region_field="region")
    qs = filters.apply_case_filters(qs)
    qs = filters.apply_gender(qs)

    by_status = list(qs.values("current_status").annotate(count=Count("id")))
    by_priority = list(qs.values("priority_level").annotate(count=Count("id")))
    region_labels, region_values = an.region_wise(qs)
    local_labels, local_values = an.local_council_wise(qs, limit=5)
    jk_labels, jk_values = an.jamat_khana_wise(qs, limit=5)
    month_labels, month_values = an.monthly_trend(qs, date_field="referral_date")
    year_labels, year_values = an.yearly_trend(qs, date_field="referral_date")
    by_source = list(qs.values("referral_source").annotate(c=Count("id")).order_by("-c")[:10])

    closed_with_dates = qs.filter(current_status="CLOSED").annotate(
        updated_date=TruncDate("updated_at"),
    ).annotate(
        duration=ExpressionWrapper(F("updated_date") - F("referral_date"), output_field=DurationField())
    )
    avg_days = closed_with_dates.aggregate(a=Avg("duration"))["a"]
    avg_days_to_closure = avg_days.days if avg_days else None

    total_cases = qs.count()
    closed_cases = qs.filter(current_status="CLOSED").count()
    by_manager = list(qs.exclude(assigned_case_manager__isnull=True).values(
        "assigned_case_manager__username"
    ).annotate(c=Count("id")).order_by("-c")[:8])

    return {
        "filters": filters,
        "total_cases": total_cases,
        "open_cases": qs.exclude(current_status="CLOSED").count(),
        "closed_cases": closed_cases,
        "closure_rate": an.pct(closed_cases, total_cases),
        "avg_days_to_closure": avg_days_to_closure,
        "status_labels": [s["current_status"] for s in by_status], "status_values": [s["count"] for s in by_status],
        "priority_labels": [p["priority_level"] for p in by_priority], "priority_values": [p["count"] for p in by_priority],
        "region_labels": region_labels, "region_values": region_values,
        "local_labels": local_labels, "local_values": local_values,
        "jk_labels": jk_labels, "jk_values": jk_values,
        "month_labels": month_labels, "month_values": month_values,
        "year_labels": year_labels, "year_values": year_values,
        "source_labels": [s["referral_source"] or "Unspecified" for s in by_source], "source_values": [s["c"] for s in by_source],
        "by_manager": by_manager,
        "records": qs.select_related("participant", "region").order_by("-referral_date"),
    }


class CaseDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/case_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        data = _case_data(self.request)
        for key in ("status_labels", "status_values", "priority_labels", "priority_values", "region_labels",
                    "region_values", "local_labels", "local_values", "jk_labels", "jk_values",
                    "month_labels", "month_values", "year_labels", "year_values",
                    "source_labels", "source_values"):
            ctx[key] = an.chart_json(data[key])
        ctx.update({k: v for k, v in data.items() if k not in ctx})
        ctx.update(_geo_filter_context(self.request))
        ctx["status_choices"] = CaseRecord.Status.choices
        ctx["priority_choices"] = CaseRecord.Priority.choices
        ctx["export_qs"] = data["filters"].querystring()
        return ctx


class CaseListView(LoginRequiredMixin, ListView):
    model = CaseRecord
    template_name = "dashboard/case_list.html"
    context_object_name = "cases"
    paginate_by = 25

    def get_queryset(self):
        qs = scope_qs(self.request.user, CaseRecord.objects.select_related("participant", "region"))
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(current_status=status)
        return qs.order_by("-referral_date")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = CaseRecord.Status.choices
        return ctx


class CaseCreateView(LoginRequiredMixin, CreateView):
    """Backend retained for direct-URL/admin use; not linked from the UI."""
    model = CaseRecord
    form_class = CaseRecordForm
    template_name = "dashboard/case_form.html"
    success_url = reverse_lazy("dashboard:case_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        log_action(self.request, AuditLog.Action.CREATE, "CaseRecord", self.object.pk, str(self.object))
        messages.success(self.request, f"Case {self.object.case_id} created.")
        return response


class CaseDetailView(LoginRequiredMixin, DetailView):
    model = CaseRecord
    template_name = "dashboard/case_detail.html"
    context_object_name = "case"

    def get_queryset(self):
        return scope_qs(self.request.user, CaseRecord.objects.all())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["follow_up_form"] = CaseFollowUpForm()
        ctx["follow_ups"] = self.object.follow_ups.all()
        return ctx


class CaseFollowUpCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        case = get_object_or_404(scope_qs(request.user, CaseRecord.objects.all()), pk=pk)
        form = CaseFollowUpForm(request.POST)
        if form.is_valid():
            follow_up = form.save(commit=False)
            follow_up.case = case
            follow_up.created_by = request.user
            follow_up.save()
            log_action(request, AuditLog.Action.CREATE, "CaseFollowUp", follow_up.pk, str(follow_up))
            messages.success(request, "Follow-up recorded.")
        else:
            messages.error(request, "Please correct the errors in the follow-up form.")
        return redirect("dashboard:case_detail", pk=pk)


class CaseUpdateView(LoginRequiredMixin, UpdateView):
    model = CaseRecord
    form_class = CaseRecordForm
    template_name = "dashboard/case_form.html"

    def get_queryset(self):
        return scope_qs(self.request.user, CaseRecord.objects.all())

    def get_success_url(self):
        return reverse("dashboard:case_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request, AuditLog.Action.UPDATE, "CaseRecord", self.object.pk, str(self.object))
        return response


class ExportCasesCSVView(LoginRequiredMixin, View):
    def get(self, request):
        data = _case_data(request)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="cases_{timezone.now():%Y%m%d}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Case ID", "Participant", "Region", "Referral Date", "Source", "Reason", "Priority", "Status", "Closed"])
        for c in data["records"]:
            writer.writerow([c.case_id, c.participant.full_name, c.region.name, c.referral_date, c.referral_source, c.reason_for_referral, c.get_priority_level_display(), c.get_current_status_display(), "Yes" if c.closure_status else "No"])
        return response


class ExportCasePDFView(LoginRequiredMixin, View):
    def get(self, request):
        data = _case_data(request)
        status_display = dict(CaseRecord.Status.choices)
        priority_display = dict(CaseRecord.Priority.choices)
        kpis = [
            ("Total Cases", data["total_cases"]),
            ("Open / Follow-up", data["open_cases"]),
            ("Closed", f'{data["closed_cases"]} ({data["closure_rate"]}%)'),
            ("Avg. Days to Closure", data["avg_days_to_closure"] if data["avg_days_to_closure"] is not None else "N/A"),
        ]
        charts = [
            {"type": "line", "title": "Monthly Trend", "labels": data["month_labels"], "values": data["month_values"]},
            {"type": "pie", "title": "By Status", "labels": [status_display.get(s, s) for s in data["status_labels"]], "values": data["status_values"]},
            {"type": "bar", "title": "By Priority", "labels": [priority_display.get(p, p) for p in data["priority_labels"]], "values": data["priority_values"]},
            {"type": "barh", "title": "Top Referral Sources", "labels": data["source_labels"], "values": data["source_values"]},
        ]
        tables = [
            {"title": "Region-wise Analysis", "headers": ["Region", "Cases"], "rows": list(zip(data["region_labels"], data["region_values"]))},
            {"title": "Case Manager Workload", "headers": ["Case Manager", "Assigned Cases"], "rows": [[m["assigned_case_manager__username"], m["c"]] for m in data["by_manager"]]},
        ]
        pdf = build_dashboard_pdf(
            "Case Management & Referrals Dashboard", "Integrated Health Programs Data Management System",
            kpis, charts, tables, filters_summary=_filters_summary(data["filters"]),
        )
        return _pdf_response(pdf, f"case_dashboard_{timezone.now():%Y%m%d}.pdf")


# ===========================================================================
# BUDGET ALLOCATIONS (National Admins only) - unaffected by dashboard filters
# ===========================================================================
class BudgetAllocationListView(NationalOnlyMixin, ListView):
    model = BudgetAllocation
    template_name = "dashboard/budget_list.html"
    context_object_name = "allocations"

    def get_queryset(self):
        return BudgetAllocation.objects.select_related("portfolio", "region").all()


class BudgetAllocationCreateView(NationalOnlyMixin, CreateView):
    model = BudgetAllocation
    form_class = BudgetAllocationForm
    template_name = "dashboard/budget_form.html"
    success_url = reverse_lazy("dashboard:budget_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        log_action(self.request, AuditLog.Action.CREATE, "BudgetAllocation", self.object.pk, str(self.object))
        messages.success(self.request, "Budget allocation saved.")
        return response


# ===========================================================================
# BULK UPLOAD (Excel / CSV)
# ===========================================================================
class DownloadUploadTemplateView(RoleRequiredMixin, View):
    """Form-type-specific downloadable .xlsx template (correct headers only)
    for the Bulk Upload page, so uploaders always start from a file that
    matches exactly what the importer for that form type expects."""
    allowed_roles = UPLOADER_ROLES

    def get(self, request, form_type):
        buf = build_upload_template(form_type)
        if buf is None:
            messages.error(request, "Unknown form type - couldn't build a template for it.")
            return redirect("dashboard:upload_add")
        label = dict(UploadBatch.FormType.choices).get(form_type, form_type)
        filename = f"{form_type}_template.xlsx"
        response = HttpResponse(
            buf.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class UploadCreateView(RoleRequiredMixin, View):
    allowed_roles = UPLOADER_ROLES
    template_name = "dashboard/upload_form.html"

    def get(self, request):
        return render(request, self.template_name, {"form": UploadForm()})

    def post(self, request):
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            batch = form.save(commit=False)
            batch.created_by = request.user
            batch.save()
            process_upload_batch(batch)
            log_action(
                request, AuditLog.Action.IMPORT, "UploadBatch", batch.pk,
                f"{batch.get_form_type_display()}: {batch.success_count} ok / {batch.error_count} errors",
            )
            if batch.error_count:
                messages.warning(request, f"Upload completed with {batch.error_count} error(s). {batch.success_count} row(s) imported successfully.")
            else:
                messages.success(request, f"Upload completed successfully. {batch.success_count} row(s) imported.")
            return redirect("dashboard:upload_detail", pk=batch.pk)
        return render(request, self.template_name, {"form": form})


class UploadListView(RoleRequiredMixin, ListView):
    allowed_roles = UPLOADER_ROLES
    model = UploadBatch
    template_name = "dashboard/upload_list.html"
    context_object_name = "batches"
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        qs = UploadBatch.objects.select_related("created_by")
        if not (user.is_national or user.is_superuser):
            qs = qs.filter(created_by=user)
        return qs


class UploadDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = UPLOADER_ROLES
    model = UploadBatch
    template_name = "dashboard/upload_detail.html"
    context_object_name = "batch"
