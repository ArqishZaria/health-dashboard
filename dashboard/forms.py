from django import forms
from .models import UploadBatch, ActivityReport, CaseRecord, CaseFollowUp, BudgetAllocation, TrainingProgram


class UploadForm(forms.ModelForm):
    class Meta:
        model = UploadBatch
        fields = ("form_type", "file")
        widgets = {
            "form_type": forms.Select(attrs={"class": "form-select"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".xlsx,.xls,.csv"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # MULTI_SHEET is assigned automatically when an uploaded workbook
        # turns out to have more than one sheet - it's never something the
        # uploader picks beforehand, so it's excluded from this dropdown.
        self.fields["form_type"].choices = [
            (value, label) for value, label in UploadBatch.FormType.choices
            if value != UploadBatch.FormType.MULTI_SHEET
        ]

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith((".xlsx", ".xls", ".csv")):
            raise forms.ValidationError("Only .xlsx, .xls or .csv files are supported.")
        if f.size > 10 * 1024 * 1024:
            raise forms.ValidationError("File too large (max 10 MB).")
        return f


class ActivityReportForm(forms.ModelForm):
    class Meta:
        model = ActivityReport
        fields = "__all__"
        exclude = ("created_by",)
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "description": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "remarks": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-select" if isinstance(field.widget, forms.Select) else "form-control")


class CaseRecordForm(forms.ModelForm):
    class Meta:
        model = CaseRecord
        exclude = ("created_by", "case_id")
        widgets = {
            "referral_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "case_outcome": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-select" if isinstance(field.widget, forms.Select) else "form-control")


class CaseFollowUpForm(forms.ModelForm):
    class Meta:
        model = CaseFollowUp
        exclude = ("created_by", "case")
        widgets = {
            "follow_up_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "next_reminder_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "consultation_details": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "investigation_results": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "treatment_initiated": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }


class BudgetAllocationForm(forms.ModelForm):
    class Meta:
        model = BudgetAllocation
        exclude = ("created_by",)
        widgets = {
            "fiscal_year": forms.NumberInput(attrs={"class": "form-control"}),
            "allocated_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-select" if isinstance(field.widget, forms.Select) else "form-control")


class TrainingProgramForm(forms.ModelForm):
    class Meta:
        model = TrainingProgram
        exclude = ("created_by",)
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-select" if isinstance(field.widget, forms.Select) else "form-control")
