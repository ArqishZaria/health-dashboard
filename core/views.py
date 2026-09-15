from django.contrib.auth import login, logout
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, View
from django.http import HttpResponseRedirect

from .forms import StyledAuthenticationForm, UserCreateForm, UserEditForm
from .models import User, Region, AuditLog
from .permissions import NationalOnlyMixin
from .middleware import log_action


class AppLoginView(LoginView):
    template_name = "core/login.html"
    authentication_form = StyledAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request, AuditLog.Action.LOGIN, "User", self.request.user.pk, "User logged in")
        return response


@login_required
def app_logout(request):
    log_action(request, AuditLog.Action.LOGOUT, "User", request.user.pk, "User logged out")
    logout(request)
    return redirect("core:login")


@login_required
def profile(request):
    return render(request, "core/profile.html", {"profile_user": request.user})


# ---------------------------------------------------------------------------
# User management (National Admins only)
# ---------------------------------------------------------------------------
class UserListView(NationalOnlyMixin, ListView):
    model = User
    template_name = "core/user_list.html"
    context_object_name = "users"
    paginate_by = 25

    def get_queryset(self):
        qs = User.objects.select_related("region", "local_council").all()
        q = self.request.GET.get("q")
        role = self.request.GET.get("role")
        if q:
            qs = qs.filter(username__icontains=q)
        if role:
            qs = qs.filter(role=role)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["role_choices"] = User.Role.choices
        return ctx


class UserCreateView(NationalOnlyMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = "core/user_form.html"
    success_url = reverse_lazy("core:user_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request, AuditLog.Action.CREATE, "User", self.object.pk, f"Created user {self.object.username}")
        messages.success(self.request, f"User '{self.object.username}' created successfully.")
        return response


class UserEditView(NationalOnlyMixin, UpdateView):
    model = User
    form_class = UserEditForm
    template_name = "core/user_form.html"
    success_url = reverse_lazy("core:user_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request, AuditLog.Action.UPDATE, "User", self.object.pk, f"Updated user {self.object.username}")
        messages.success(self.request, f"User '{self.object.username}' updated successfully.")
        return response


class UserDeleteView(NationalOnlyMixin, DeleteView):
    model = User
    template_name = "core/user_confirm_delete.html"
    success_url = reverse_lazy("core:user_list")

    def form_valid(self, form):
        username = self.object.username
        response = super().form_valid(form)
        log_action(self.request, AuditLog.Action.DELETE, "User", self.object.pk, f"Deleted user {username}")
        messages.success(self.request, f"User '{username}' deleted.")
        return response


# ---------------------------------------------------------------------------
# Geography management (National Admins only)
# ---------------------------------------------------------------------------
class RegionListView(NationalOnlyMixin, ListView):
    model = Region
    template_name = "core/region_list.html"
    context_object_name = "regions"


class AuditLogListView(NationalOnlyMixin, ListView):
    model = AuditLog
    template_name = "core/audit_log_list.html"
    context_object_name = "logs"
    paginate_by = 50

    def get_queryset(self):
        return AuditLog.objects.select_related("user").all()
