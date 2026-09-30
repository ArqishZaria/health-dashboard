from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.exceptions import ValidationError
import re

def _unique_code(model, base, max_len=20):
    base = re.sub(r"[^A-Z0-9]+", "", (base or "").upper())[: max_len - 4] or "X"
    code, n = base, 1
    while model.objects.filter(code=code).exists():
        n += 1
        code = f"{base}{n}"
    return code


class Region(models.Model):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=20, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = _unique_code(Region, self.name[:3])
        super().save(*args, **kwargs)


class LocalCouncil(models.Model):
    code = models.CharField(max_length=20, unique=True, blank=True)
    name = models.CharField(max_length=150)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name="local_councils")

    class Meta:
        ordering = ["region__name", "name"]
        unique_together = ("region", "name")

    def __str__(self):
        return f"{self.name} ({self.region.name})"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = _unique_code(LocalCouncil, f"{self.region.code}{self.name[:8]}")
        super().save(*args, **kwargs)


class JamatKhana(models.Model):
    code = models.CharField(max_length=20, unique=True, blank=True)
    name = models.CharField(max_length=150)
    local_council = models.ForeignKey(LocalCouncil, on_delete=models.CASCADE, related_name="jamat_khanas")

    class Meta:
        ordering = ["local_council__name", "name"]
        unique_together = ("local_council", "name")
        verbose_name = "Jamatkhana"
        verbose_name_plural = "Jamatkhanas"

    def __str__(self):
        return f"{self.name}"

    @property
    def region(self):
        return self.local_council.region

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = _unique_code(JamatKhana, f"{self.local_council.code}{self.name[:8]}")
        super().save(*args, **kwargs)


class Portfolio(models.Model):
    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Case-insensitive de-dup guard: prevents "Health screening" and
        # "Health Screening" becoming two rows via bulk-upload / admin.
        if not self.pk:
            existing = Portfolio.objects.filter(name__iexact=self.name).first()
            if existing:
                self.pk = existing.pk
        super().save(*args, **kwargs)


class Program(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="programs")
    name = models.CharField(max_length=150)

    class Meta:
        ordering = ["portfolio__name", "name"]
        unique_together = ("portfolio", "name")

    def __str__(self):
        return f"{self.name}"

    def save(self, *args, **kwargs):
        if not self.pk:
            existing = Program.objects.filter(portfolio=self.portfolio, name__iexact=self.name).first()
            if existing:
                self.pk = existing.pk
        super().save(*args, **kwargs)


class User(AbstractUser):
    """
    Custom user model with role-based, geography-scoped access.

    ROLE HIERARCHY (broad -> narrow):
      NATIONAL   - sees & manages data across all regions
      REGIONAL   - sees & manages data only within their assigned Region
      LOCAL      - sees & manages data only within their assigned Local Council
      DATA_ENTRY - can enter/upload data for their assigned Local Council only
      VIEWER     - read-only access, scoped like REGIONAL/LOCAL depending on assignment
    """

    class Role(models.TextChoices):
        NATIONAL = "NATIONAL", "National Admin"
        REGIONAL = "REGIONAL", "Regional Coordinator"
        LOCAL = "LOCAL", "Local Council Officer"
        DATA_ENTRY = "DATA_ENTRY", "Data Entry Operator"
        VIEWER = "VIEWER", "Viewer (Read-only)"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.DATA_ENTRY)

    region = models.ForeignKey(
        Region, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="users",
        help_text="Required for REGIONAL role and below (scopes visible data).",
    )
    local_council = models.ForeignKey(
        LocalCouncil, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="users",
        help_text="Required for LOCAL / DATA_ENTRY roles.",
    )
    phone_number = models.CharField(max_length=30, blank=True)
    designation = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"

    def clean(self):
        super().clean()
        # Superusers (e.g. createsuperuser, which defaults role=DATA_ENTRY
        # with no local council) are exempt from role/geography validation -
        # otherwise they become un-editable in both Django Admin and the
        # in-app user-management forms.
        if self.is_superuser:
            return
        if self.role == self.Role.REGIONAL and not self.region_id:
            raise ValidationError("Regional users must be assigned a Region.")
        if self.role in (self.Role.LOCAL, self.Role.DATA_ENTRY) and not self.local_council_id:
            raise ValidationError("Local/Data-entry users must be assigned a Local Council.")

    @property
    def is_national(self):
        return self.role == self.Role.NATIONAL or self.is_superuser

    @property
    def is_regional(self):
        return self.role == self.Role.REGIONAL

    @property
    def is_local(self):
        return self.role in (self.Role.LOCAL, self.Role.DATA_ENTRY)

    @property
    def can_upload(self):
        return self.is_superuser or self.role in (
            self.Role.NATIONAL, self.Role.REGIONAL, self.Role.LOCAL, self.Role.DATA_ENTRY
        )

    @property
    def can_manage_users(self):
        return self.is_national

    def scope_label(self):
        if self.is_national:
            return "All Regions"
        if self.region_id and self.role == self.Role.REGIONAL:
            return str(self.region)
        if self.local_council_id:
            return str(self.local_council)
        return "Unassigned"


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"
        IMPORT = "IMPORT", "Bulk Import"
        LOGIN = "LOGIN", "Login"
        LOGOUT = "LOGOUT", "Logout"

    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="audit_logs")
    action = models.CharField(max_length=20, choices=Action.choices)
    model_name = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp} - {self.user} - {self.action} - {self.model_name}"