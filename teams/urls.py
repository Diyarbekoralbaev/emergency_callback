from django.urls import path
from . import views

app_name = 'teams'

urlpatterns = [
    path('', views.team_list, name='list'),
    path('create/', views.team_create, name='create'),
    path('<int:pk>/', views.team_detail, name='detail'),
    path('<int:pk>/edit/', views.team_edit, name='edit'),
    path('<int:pk>/delete/', views.team_delete, name='delete'),

    # API endpoints
    path('<int:pk>/stats/', views.team_stats_api, name='stats_api'),
]