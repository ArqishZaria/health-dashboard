from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.exceptions import ValidationError


class Region(models.Model):
    """Top-level geography. e.g. Karachi, Sindh, Punjab, etc."""
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=20, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.name[:3].upper()
        super().save(*args, **kwargs)


class LocalCouncil(models.Model):
    """Local Council belongs to a Region."""
    code = models.CharField(max_length=20, unique=True, blank=True)
    name = models.CharField(max_length=150)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name="local_councils")
    class Meta:
        ordering = ["region__name", "name"]
        unique_together = ("region", "name")

    def __str__(self):
        return f"{self.name} ({self.region.name})"


class JamatKhana(models.Model):
    """Venue / Jamatkhana belongs to a Local Council."""
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


class Portfolio(models.Model):
    """Health Board portfolio, e.g. Health Screening, Training, Community Health."""
    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Program(models.Model):
    """Program under a Portfolio, e.g. Cardiac Risk Assessment."""
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="programs")
    name = models.CharField(max_length=150)

    class Meta:
        ordering = ["portfolio__name", "name"]
        unique_together = ("portfolio", "name")

    def __str__(self):
        return f"{self.name}"


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
    """Generic audit trail for edits / uploads / logins across the system."""

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
