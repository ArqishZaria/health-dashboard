from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, UserChangeForm
from .models import User


class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"class": "form-control", "placeholder": "Username", "autofocus": True})
        self.fields["password"].widget.attrs.update({"class": "form-control", "placeholder": "Password"})


class UserCreateForm(UserCreationForm):
    class Meta:
        model = User
        fields = (
            "username", "first_name", "last_name", "email", "phone_number",
            "designation", "role", "region", "local_council", "password1", "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        region = cleaned.get("region")
        local_council = cleaned.get("local_council")
        if role == User.Role.REGIONAL and not region:
            self.add_error("region", "Region is required for Regional Coordinator role.")
        if role in (User.Role.LOCAL, User.Role.DATA_ENTRY) and not local_council:
            self.add_error("local_council", "Local Council is required for this role.")
        return cleaned


class UserEditForm(UserChangeForm):
    password = None

    class Meta:
        model = User
        fields = (
            "username", "first_name", "last_name", "email", "phone_number",
            "designation", "role", "region", "local_council", "is_active",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")



