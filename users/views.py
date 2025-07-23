from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import UserRoleChoices


def user_login(request):
    if request.user.is_authenticated:
        # If user is already logged in, redirect based on role
        if request.user.role == UserRoleChoices.ADMIN:
            return redirect('callbacks:dashboard')
        else:
            return redirect('callbacks:list')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        if username and password:
            user = authenticate(request, username=username, password=password)

            if user is not None:
                login(request, user)

                # Role-based redirect after successful login
                if user.role == UserRoleChoices.ADMIN:
                    messages.success(request, f'Добро пожаловать, {user.username}! Вы вошли как администратор.')
                    return redirect('callbacks:dashboard')
                else:
                    messages.success(request, f'Добро пожаловать, {user.username}! Вы вошли как оператор.')
                    return redirect('callbacks:list')
            else:
                messages.error(request, 'Неверное имя пользователя или пароль.')
        else:
            messages.error(request, 'Пожалуйста, заполните все поля.')

    return render(request, 'users/login.html')


@login_required
def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('users:login')