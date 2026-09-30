from django import forms
from .models import UploadBatch, ActivityReport, CaseRecord, CaseFollowUp, BudgetAllocation, TrainingProgram, Participant
from .filters import region_choices, local_council_choices, jamat_khana_choices
from .utils import scope_qs


class UploadForm(forms.ModelForm):
    class Meta:
        model = UploadBatch
        fields = ("form_type", "file")
        widgets = {
            "form_type": forms.Select(attrs={"class": "form-select"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".xlsx,.xls,.csv"}),
        }

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith((".xlsx", ".xls", ".csv")):
            raise forms.ValidationError("Only .xlsx, .xls or .csv files are supported.")
        if f.size > 10 * 1024 * 1024:
            raise forms.ValidationError("File too large (max 10 MB).")
        return f


class ScopedGeoFormMixin:
    """
    Mix into any ModelForm with region / local_council / jamat_khana
    fields to:
      1. Restrict the dropdown choices to the requesting user's scope
         (so a Regional Coordinator can't reassign a record outside their
         Region via a crafted POST, not just hide the option in the UI).
      2. Validate that local_council actually belongs to region, and
         jamat_khana actually belongs to local_council - the form
         previously allowed any combination.
    Views using this mixin MUST pass user=request.user via get_form_kwargs().
    """
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._scoping_user = user
        if user and not (user.is_superuser or user.is_national):
            if "region" in self.fields:
                self.fields["region"].queryset = region_choices(user)
            if "local_council" in self.fields:
                self.fields["local_council"].queryset = local_council_choices(user)
            if "jamat_khana" in self.fields:
                self.fields["jamat_khana"].queryset = jamat_khana_choices(user)
            if "participant" in self.fields:
                self.fields["participant"].queryset = scope_qs(user, Participant.objects.all())

    def clean(self):
        cleaned = super().clean()
        region = cleaned.get("region")
        local_council = cleaned.get("local_council")
        jamat_khana = cleaned.get("jamat_khana")

        if region and local_council and local_council.region_id != region.id:
            self.add_error("local_council", "This Local Council doesn't belong to the selected Region.")
        if local_council and jamat_khana and jamat_khana.local_council_id != local_council.id:
            self.add_error("jamat_khana", "This Jamatkhana doesn't belong to the selected Local Council.")

        user = self._scoping_user
        if user and not (user.is_superuser or user.is_national) and region:
            if user.role == user.Role.REGIONAL and user.region_id and region.id != user.region_id:
                self.add_error("region", "You can only enter data for your assigned Region.")
            elif user.local_council_id and local_council and local_council.id != user.local_council_id:
                self.add_error("local_council", "You can only enter data for your assigned Local Council.")
        return cleaned


class ActivityReportForm(ScopedGeoFormMixin, forms.ModelForm):
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


class CaseRecordForm(ScopedGeoFormMixin, forms.ModelForm):
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")


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


class TrainingProgramForm(ScopedGeoFormMixin, forms.ModelForm):
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