"""
dashboard app models.

Covers every module in the requirements document:
  - Activity Reporting Tool
  - Health Screening Programs (10 screening tools, common demographics captured once)
  - Training & Capacity Building (+ digital attendance)
  - Case Management & Referral
  - Bulk upload tracking (UploadBatch) used by the Excel/CSV importer

Design note on screening forms
-------------------------------
Each of the 10+ screening tools shares a common demographic core (captured
once per Participant) plus a handful of common outcome fields (referred,
risk category, remarks). Beyond that, every tool has its own set of
program-specific assessment fields (see the Excel template headers).
Rather than hand-rolling 10 near-duplicate tables with 20+ columns each,
every concrete screening model:
  1. Inherits the common fields from `ScreeningRecordBase` (FK to
     Participant, date, geography, referral outcome, risk category).
  2. Stores its assessment-specific answers in a validated `details`
     JSONField, keyed exactly to that form's Excel template headers
     (declared in `TEMPLATE_FIELDS` on the model / importer).
This keeps the schema maintainable while still being fully queryable
(JSONField supports filtering) and 100% aligned to the supplied Excel
templates for bulk import.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import Region, LocalCouncil, JamatKhana, Portfolio, Program


# ---------------------------------------------------------------------------
# Shared mixins
# ---------------------------------------------------------------------------
class GeoScopedModel(models.Model):
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="+")
    local_council = models.ForeignKey(LocalCouncil, on_delete=models.PROTECT, related_name="+")
    jamat_khana = models.ForeignKey(JamatKhana, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        abstract = True


class AuditedModel(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# 2. Activity Reporting Tool
# ---------------------------------------------------------------------------
class ActivityReport(GeoScopedModel, AuditedModel):
    date = models.DateField()
    venue = models.CharField(max_length=200)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT, related_name="activity_reports")
    program = models.ForeignKey(Program, on_delete=models.PROTECT, related_name="activity_reports")
    name_of_activity = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    number_of_beneficiaries = models.PositiveIntegerField(default=0)
    facilitator_trainer = models.CharField(max_length=200, blank=True)
    collaboration = models.CharField(max_length=250, blank=True)
    supporting_photograph = models.FileField(upload_to="activity_reports/photos/", null=True, blank=True)
    supporting_document = models.FileField(upload_to="activity_reports/docs/", null=True, blank=True)
    cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Actual amount spent/utilized on this activity (for budget utilization reporting).",
    )
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-date"]
        indexes = [models.Index(fields=["date", "region", "portfolio", "program"])]

    def __str__(self):
        return f"{self.name_of_activity} - {self.date}"


# ---------------------------------------------------------------------------
# 3. Health Screening Programs - shared demographic entity
# ---------------------------------------------------------------------------
class Participant(GeoScopedModel, AuditedModel):
    GENDER_CHOICES = (("M", "Male"), ("F", "Female"), ("O", "Other"))

    participant_uid = models.CharField(max_length=20, unique=True, editable=False)
    full_name = models.CharField(max_length=200)
    father_husband_name = models.CharField(max_length=200, blank=True)
    cnic = models.CharField(max_length=20, blank=True, db_index=True)
    contact_number = models.CharField(max_length=30, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    date_of_birth = models.DateField(null=True, blank=True)
    age = models.PositiveIntegerField(null=True, blank=True)
    venue = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["cnic"]), models.Index(fields=["full_name"])]

    def __str__(self):
        return f"{self.full_name} ({self.participant_uid})"

    def save(self, *args, **kwargs):
        if not self.participant_uid:
            self.participant_uid = f"P-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)


class ScreeningRecordBase(GeoScopedModel, AuditedModel):
    RISK_CHOICES = (("LOW", "Low"), ("MODERATE", "Moderate"), ("HIGH", "High"), ("UNKNOWN", "Not Assessed"))

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="%(class)s_records")
    program = models.ForeignKey(
        Program, null=True, blank=True, on_delete=models.SET_NULL, related_name="%(class)s_records",
        help_text="Screening program this record belongs to (auto-linked under the Health Screening portfolio).",
    )
    screening_date = models.DateField(default=timezone.now)
    source = models.CharField(max_length=20, default="AKHSP", help_text="Data source system, e.g. Kobo / AKHSP")
    risk_category = models.CharField(max_length=10, choices=RISK_CHOICES, default="UNKNOWN")
    referred = models.BooleanField(default=False)
    reason_for_referral = models.CharField(max_length=250, blank=True)
    details = models.JSONField(default=dict, blank=True, help_text="Program-specific fields matching the Excel template")
    remarks = models.TextField(blank=True)

    class Meta:
        abstract = True
        ordering = ["-screening_date"]

    def __str__(self):
        return f"{self.participant.full_name} - {self.screening_date}"


class CardiacRiskAssessment(ScreeningRecordBase):
    """Cardiac Risk Assessment (Kobo + AKHSP templates)."""
    class Meta(ScreeningRecordBase.Meta):
        verbose_name = "Cardiac Risk Assessment"


class MentalHealthDASS21(ScreeningRecordBase):
    """Mental Health (DASS-21 Assessment)."""
    depression_score = models.IntegerField(null=True, blank=True)
    anxiety_score = models.IntegerField(null=True, blank=True)
    stress_score = models.IntegerField(null=True, blank=True)

    class Meta(ScreeningRecordBase.Meta):
        verbose_name = "Mental Health (DASS-21)"


class ClinicalBreastExamination(ScreeningRecordBase):
    class Meta(ScreeningRecordBase.Meta):
        verbose_name = "Clinical Breast Examination"


class MammogramScreening(ScreeningRecordBase):
    class Meta(ScreeningRecordBase.Meta):
        verbose_name = "Mammogram Screening"


class ElderlyEyeScreening(ScreeningRecordBase):
    class Meta(ScreeningRecordBase.Meta):
        verbose_name = "Elderly Eye Screening"


class AdolescentHealthScreening(ScreeningRecordBase):
    class Meta(ScreeningRecordBase.Meta):
        verbose_name = "Adolescent Health Screening"


class HbA1cScreening(ScreeningRecordBase):
    class Meta(ScreeningRecordBase.Meta):
        verbose_name = "HbA1c Screening"


class NutritionAssessment(ScreeningRecordBase):
    class Meta(ScreeningRecordBase.Meta):
        verbose_name = "Nutrition Assessment"


class ElderlyNeurologicalAssessment(ScreeningRecordBase):
    """Also covers ICOPE-style elderly assessment fields (stored in `details`)."""
    class Meta(ScreeningRecordBase.Meta):
        verbose_name = "Elderly Neurological Assessment"


class AdultHealthScreening(ScreeningRecordBase):
    """Covers general Camp Screening / Adult Health Screening AKHSP template."""
    class Meta(ScreeningRecordBase.Meta):
        verbose_name = "Adult Health Screening"


# Registry used by the importer, dashboards & navigation to iterate all
# screening modules generically.
SCREENING_MODELS = {
    "cardiac_risk_assessment": CardiacRiskAssessment,
    "mental_health_dass21": MentalHealthDASS21,
    "clinical_breast_examination": ClinicalBreastExamination,
    "mammogram_screening": MammogramScreening,
    "elderly_eye_screening": ElderlyEyeScreening,
    "adolescent_health_screening": AdolescentHealthScreening,
    "hba1c_screening": HbA1cScreening,
    "nutrition_assessment": NutritionAssessment,
    "elderly_neurological_assessment": ElderlyNeurologicalAssessment,
    "adult_health_screening": AdultHealthScreening,
}


# ---------------------------------------------------------------------------
# 4. Training & Capacity Building
# ---------------------------------------------------------------------------
class TrainingProgram(GeoScopedModel, AuditedModel):
    title = models.CharField(max_length=250)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT, related_name="trainings")
    program = models.ForeignKey(Program, on_delete=models.PROTECT, related_name="trainings")
    date = models.DateField()
    trainer_name = models.CharField(max_length=200)
    duration_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    target_audience = models.CharField(max_length=250, blank=True)
    number_of_participants = models.PositiveIntegerField(default=0)
    cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Actual amount spent/utilized on this training (for budget utilization reporting).",
    )

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.title} - {self.date}"


class TrainingAttendance(AuditedModel):
    ATTENDANCE_CHOICES = (("PRESENT", "Present"), ("ABSENT", "Absent"), ("PARTIAL", "Partial"))

    training = models.ForeignKey(TrainingProgram, on_delete=models.CASCADE, related_name="attendees")
    participant_name = models.CharField(max_length=200)
    cnic = models.CharField(max_length=20, blank=True)
    contact_number = models.CharField(max_length=30, blank=True)
    institution_organization = models.CharField(max_length=200, blank=True)
    designation_title = models.CharField(max_length=150, blank=True)
    signature = models.FileField(upload_to="training/signatures/", null=True, blank=True)
    attendance_status = models.CharField(max_length=10, choices=ATTENDANCE_CHOICES, default="PRESENT")

    class Meta:
        ordering = ["participant_name"]

    def __str__(self):
        return f"{self.participant_name} - {self.training.title}"


# ---------------------------------------------------------------------------
# 5. Case Management and Referral Module
# ---------------------------------------------------------------------------
class CaseRecord(GeoScopedModel, AuditedModel):
    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In Progress / Follow-up"
        PENDING = "PENDING", "Pending"
        CLOSED = "CLOSED", "Closed"

    case_id = models.CharField(max_length=20, unique=True, editable=False)
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="cases")
    referral_date = models.DateField()
    referral_source = models.CharField(max_length=150, help_text="Screening program the referral originated from")
    reason_for_referral = models.CharField(max_length=250)
    referral_facility_doctor = models.CharField(max_length=200, blank=True)
    assigned_case_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_cases"
    )
    priority_level = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    current_status = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN)
    case_outcome = models.TextField(blank=True)
    closure_status = models.BooleanField(default=False)

    class Meta:
        ordering = ["-referral_date"]

    def __str__(self):
        return f"{self.case_id} - {self.participant.full_name}"

    def save(self, *args, **kwargs):
        if not self.case_id:
            self.case_id = f"CASE-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)


class CaseFollowUp(AuditedModel):
    case = models.ForeignKey(CaseRecord, on_delete=models.CASCADE, related_name="follow_ups")
    follow_up_date = models.DateField()
    consultation_details = models.TextField(blank=True)
    investigation_results = models.TextField(blank=True)
    treatment_initiated = models.TextField(blank=True)
    next_reminder_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-follow_up_date"]

    def __str__(self):
        return f"Follow-up {self.follow_up_date} - {self.case.case_id}"


# ---------------------------------------------------------------------------
# Bulk Excel/CSV Upload tracking
# ---------------------------------------------------------------------------
class BudgetAllocation(AuditedModel):
    """
    Planned budget per Portfolio (optionally narrowed to a Region) for a
    given fiscal year. Compared against the actual `cost` recorded on
    ActivityReport / TrainingProgram entries to compute Budget Utilization
    on the dashboards.
    """
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="budget_allocations")
    region = models.ForeignKey(
        Region, null=True, blank=True, on_delete=models.CASCADE, related_name="budget_allocations",
        help_text="Leave blank for a national/all-region allocation for this portfolio.",
    )
    fiscal_year = models.PositiveIntegerField(default=timezone.now().year)
    allocated_amount = models.DecimalField(max_digits=14, decimal_places=2)
    notes = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["-fiscal_year", "portfolio__name"]
        unique_together = ("portfolio", "region", "fiscal_year")

    def __str__(self):
        scope = self.region.name if self.region else "All Regions"
        return f"{self.portfolio.name} - {scope} - FY{self.fiscal_year}"


class UploadBatch(AuditedModel):
    class FormType(models.TextChoices):
        ACTIVITY_REPORT = "ACTIVITY_REPORT", "Activity Report"
        CARDIAC_RISK_ASSESSMENT = "cardiac_risk_assessment", "Cardiac Risk Assessment"
        MENTAL_HEALTH_DASS21 = "mental_health_dass21", "Mental Health (DASS-21)"
        CLINICAL_BREAST_EXAMINATION = "clinical_breast_examination", "Clinical Breast Examination"
        MAMMOGRAM_SCREENING = "mammogram_screening", "Mammogram Screening"
        ELDERLY_EYE_SCREENING = "elderly_eye_screening", "Elderly Eye Screening"
        ADOLESCENT_HEALTH_SCREENING = "adolescent_health_screening", "Adolescent Health Screening"
        HBA1C_SCREENING = "hba1c_screening", "HbA1c Screening"
        NUTRITION_ASSESSMENT = "nutrition_assessment", "Nutrition Assessment"
        ELDERLY_NEUROLOGICAL_ASSESSMENT = "elderly_neurological_assessment", "Elderly Neurological Assessment"
        ADULT_HEALTH_SCREENING = "adult_health_screening", "Adult Health Screening"
        TRAINING_ATTENDANCE = "TRAINING_ATTENDANCE", "Training Attendance"
        MULTI_SHEET = "MULTI_SHEET", "Multi-sheet (auto-detected per tab)"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS", "Completed with errors"
        FAILED = "FAILED", "Failed"

    form_type = models.CharField(max_length=50, choices=FormType.choices)
    file = models.FileField(upload_to="uploads/%Y/%m/")
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.PENDING)
    total_rows = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    error_log = models.JSONField(default=list, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_form_type_display()} upload by {self.created_by} ({self.status})"
