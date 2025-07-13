from django.urls import path
from . import views

app_name = 'callbacks'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('callbacks/', views.callback_list, name='list'),
    path('callbacks/create/', views.callback_create, name='create'),
    path('callbacks/<int:pk>/', views.callback_detail, name='detail'),
    path('ratings/', views.ratings_list, name='ratings'),
    path('get-teams-by-region/', views.get_teams_by_region, name='get_teams_by_region'),

]