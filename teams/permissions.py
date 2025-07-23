from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps
from users.models import UserRoleChoices


def admin_required(view_func):
    """Decorator that restricts access to admin users only"""

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')

        if request.user.role != UserRoleChoices.ADMIN:
            messages.error(request, 'У вас нет прав доступа к этой странице.')
            return redirect('callbacks:list')  # Redirect to call list instead

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def has_role(required_roles):
    """Decorator that checks if user has one of the required roles"""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('users:login')

            if isinstance(required_roles, str):
                roles = [required_roles]
            else:
                roles = required_roles

            if request.user.role not in roles:
                messages.error(request, 'У вас нет прав доступа к этой странице.')
                return redirect('callbacks:list')  # Redirect to call list instead

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator