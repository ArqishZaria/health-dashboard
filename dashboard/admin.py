from django.contrib import admin
from .models import (
    ActivityReport, Participant, TrainingProgram, TrainingAttendance,
    CaseRecord, CaseFollowUp, UploadBatch, BudgetAllocation,
    CardiacRiskAssessment, MentalHealthDASS21, ClinicalBreastExamination,
    MammogramScreening, ElderlyEyeScreening, AdolescentHealthScreening,
    HbA1cScreening, NutritionAssessment, ElderlyNeurologicalAssessment,
    AdultHealthScreening,
)


@admin.register(BudgetAllocation)
class BudgetAllocationAdmin(admin.ModelAdmin):
    list_display = ("portfolio", "region", "fiscal_year", "allocated_amount")
    list_filter = ("portfolio", "region", "fiscal_year")


@admin.register(ActivityReport)
class ActivityReportAdmin(admin.ModelAdmin):
    list_display = ("name_of_activity", "date", "region", "portfolio", "program", "number_of_beneficiaries", "cost")
    list_filter = ("region", "portfolio", "program", "date")
    search_fields = ("name_of_activity", "venue")


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("participant_uid", "full_name", "cnic", "gender", "age", "region", "local_council")
    list_filter = ("region", "gender")
    search_fields = ("full_name", "cnic", "participant_uid")


class ScreeningAdminBase(admin.ModelAdmin):
    list_display = ("participant", "screening_date", "program", "region", "local_council", "referred", "risk_category")
    list_filter = ("region", "referred", "risk_category")
    search_fields = ("participant__full_name", "participant__cnic")


for m in [
    CardiacRiskAssessment, MentalHealthDASS21, ClinicalBreastExamination,
    MammogramScreening, ElderlyEyeScreening, AdolescentHealthScreening,
    HbA1cScreening, NutritionAssessment, ElderlyNeurologicalAssessment,
    AdultHealthScreening,
]:
    admin.site.register(m, ScreeningAdminBase)


@admin.register(TrainingProgram)
class TrainingProgramAdmin(admin.ModelAdmin):
    list_display = ("title", "date", "region", "portfolio", "program", "number_of_participants", "cost")
    list_filter = ("region", "portfolio")
    search_fields = ("title",)


@admin.register(TrainingAttendance)
class TrainingAttendanceAdmin(admin.ModelAdmin):
    list_display = ("participant_name", "training", "attendance_status")
    list_filter = ("attendance_status",)
    search_fields = ("participant_name", "cnic")


@admin.register(CaseRecord)
class CaseRecordAdmin(admin.ModelAdmin):
    list_display = ("case_id", "participant", "current_status", "priority_level", "referral_date")
    list_filter = ("current_status", "priority_level", "region")
    search_fields = ("case_id", "participant__full_name")


@admin.register(CaseFollowUp)
class CaseFollowUpAdmin(admin.ModelAdmin):
    list_display = ("case", "follow_up_date")


@admin.register(UploadBatch)
class UploadBatchAdmin(admin.ModelAdmin):
    list_display = ("form_type", "status", "total_rows", "success_count", "error_count", "created_by", "created_at")
    list_filter = ("form_type", "status")
    readonly_fields = ("error_log", "total_rows", "success_count", "error_count", "processed_at")
