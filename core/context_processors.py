def role_context(request):
    """Expose the user's role/scope to every template for nav/UI decisions."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    return {
        "user_role_label": user.get_role_display(),
        "user_scope_label": user.scope_label(),
        "is_national_user": user.is_national,
        "is_regional_user": user.is_regional,
        "is_local_user": user.is_local,
        "can_upload_data": user.can_upload,
        "can_manage_users": user.can_manage_users,
    }
