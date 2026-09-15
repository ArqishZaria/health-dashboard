from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Region, LocalCouncil, JamatKhana, Portfolio, Program, AuditLog


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "role", "region", "local_council", "is_active", "is_staff")
    list_filter = ("role", "region", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (
        ("Role & Scope", {"fields": ("role", "region", "local_council", "phone_number", "designation")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Role & Scope", {"fields": ("role", "region", "local_council", "email", "phone_number", "designation")}),
    )


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")


@admin.register(LocalCouncil)
class LocalCouncilAdmin(admin.ModelAdmin):
    list_display = ("name", "region")
    list_filter = ("region",)
    search_fields = ("name",)


@admin.register(JamatKhana)
class JamatKhanaAdmin(admin.ModelAdmin):
    list_display = ("name", "local_council")
    list_filter = ("local_council__region",)
    search_fields = ("name",)


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "portfolio")
    list_filter = ("portfolio",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "model_name", "object_id", "ip_address")
    list_filter = ("action", "model_name")
    search_fields = ("user__username", "description")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False
