from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("login/", views.AppLoginView.as_view(), name="login"),
    path("logout/", views.app_logout, name="logout"),
    path("profile/", views.profile, name="profile"),

    path("users/", views.UserListView.as_view(), name="user_list"),
    path("users/add/", views.UserCreateView.as_view(), name="user_add"),
    path("users/<int:pk>/edit/", views.UserEditView.as_view(), name="user_edit"),
    path("users/<int:pk>/delete/", views.UserDeleteView.as_view(), name="user_delete"),

    path("regions/", views.RegionListView.as_view(), name="region_list"),

    path("audit-log/", views.AuditLogListView.as_view(), name="audit_log"),
]
