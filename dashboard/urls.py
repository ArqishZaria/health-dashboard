from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.OverviewDashboardView.as_view(), name="overview"),
    path("overview/export/csv/", views.ExportOverviewSummaryCSVView.as_view(), name="overview_export"),
    path("overview/export/pdf/", views.ExportOverviewPDFView.as_view(), name="overview_export_pdf"),

    # Activity Reporting
    path("activities/", views.ActivityReportListView.as_view(), name="activity_list"),
    path("activities/dashboard/", views.ActivityReportDashboardView.as_view(), name="activity_dashboard"),
    path("activities/add/", views.ActivityReportCreateView.as_view(), name="activity_add"),
    path("activities/<int:pk>/edit/", views.ActivityReportUpdateView.as_view(), name="activity_edit"),
    path("activities/<int:pk>/delete/", views.ActivityReportDeleteView.as_view(), name="activity_delete"),
    path("activities/export/csv/", views.ExportActivitiesCSVView.as_view(), name="activity_export"),
    path("activities/export/pdf/", views.ExportActivityPDFView.as_view(), name="activity_export_pdf"),

    # Screening programs
    path("screening/", views.ScreeningDashboardView.as_view(), name="screening_dashboard"),
    path("screening/export/csv/", views.ExportScreeningDashboardCSVView.as_view(), name="screening_dashboard_export"),
    path("screening/export/pdf/", views.ExportScreeningPDFView.as_view(), name="screening_export_pdf"),
    path("screening/<str:model_key>/", views.ScreeningRecordListView.as_view(), name="screening_list"),
    path("screening/<str:model_key>/export/", views.ExportScreeningCSVView.as_view(), name="screening_export"),
    path("participants/", views.ParticipantListView.as_view(), name="participant_list"),
    path("participants/<int:pk>/", views.ParticipantDetailView.as_view(), name="participant_detail"),

    # Training
    path("training/", views.TrainingDashboardView.as_view(), name="training_dashboard"),
    path("training/list/", views.TrainingListView.as_view(), name="training_list"),
    path("training/add/", views.TrainingCreateView.as_view(), name="training_add"),
    path("training/<int:pk>/", views.TrainingDetailView.as_view(), name="training_detail"),
    path("training/<int:pk>/edit/", views.TrainingUpdateView.as_view(), name="training_edit"),
    path("training/export/csv/", views.ExportTrainingCSVView.as_view(), name="training_export"),
    path("training/export/pdf/", views.ExportTrainingPDFView.as_view(), name="training_export_pdf"),

    # Case management
    path("cases/", views.CaseDashboardView.as_view(), name="case_dashboard"),
    path("cases/list/", views.CaseListView.as_view(), name="case_list"),
    path("cases/add/", views.CaseCreateView.as_view(), name="case_add"),
    path("cases/<int:pk>/", views.CaseDetailView.as_view(), name="case_detail"),
    path("cases/<int:pk>/edit/", views.CaseUpdateView.as_view(), name="case_edit"),
    path("cases/<int:pk>/follow-up/", views.CaseFollowUpCreateView.as_view(), name="case_follow_up_add"),
    path("cases/export/csv/", views.ExportCasesCSVView.as_view(), name="case_export"),
    path("cases/export/pdf/", views.ExportCasePDFView.as_view(), name="case_export_pdf"),

    # Budget allocations
    path("budget/", views.BudgetAllocationListView.as_view(), name="budget_list"),
    path("budget/add/", views.BudgetAllocationCreateView.as_view(), name="budget_add"),

    path("upload/", views.UploadCreateView.as_view(), name="upload_add"),
    path("upload/template/<str:form_type>/", views.DownloadUploadTemplateView.as_view(), name="upload_template"),
    path("upload/geography-reference/", views.DownloadGeographyReferenceView.as_view(), name="geography_reference"),
    path("upload/history/", views.UploadListView.as_view(), name="upload_list"),
    path("upload/<int:pk>/", views.UploadDetailView.as_view(), name="upload_detail"),
]

