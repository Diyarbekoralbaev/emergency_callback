# teams/urls.py
from django.urls import path
from . import views

app_name = 'teams'

urlpatterns = [
    # Team URLs
    path('', views.team_list, name='list'),
    path('create/', views.team_create, name='create'),
    path('<int:pk>/', views.team_detail, name='detail'),
    path('<int:pk>/edit/', views.team_edit, name='edit'),
    path('<int:pk>/delete/', views.team_delete, name='delete'),
    path('<int:pk>/stats/', views.team_stats_api, name='stats_api'),

    # Region URLs
    path('regions/', views.region_list, name='region_list'),
    path('regions/create/', views.region_create, name='region_create'),
    path('regions/<int:pk>/', views.region_detail, name='region_detail'),
    path('regions/<int:pk>/edit/', views.region_edit, name='region_edit'),
    path('regions/<int:pk>/delete/', views.region_delete, name='region_delete'),
]