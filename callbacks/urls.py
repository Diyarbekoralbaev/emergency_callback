from django.urls import path
from . import views
from . import callbacks_vote_views

app_name = 'callbacks'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('callbacks/', views.callback_list, name='list'),
    path('callbacks/create/', views.callback_create, name='create'),
    path('callbacks/<int:pk>/', views.callback_detail, name='detail'),
    path('ratings/', views.ratings_list, name='ratings'),
    path('get-teams-by-region/', views.get_teams_by_region, name='get_teams_by_region'),
    path('api/create/', views.api_callback_create, name='api_callback_create'),
    path('export-excel/', views.export_excel, name='export_excel'),

    path('vote/<uuid:vote_uuid>/', callbacks_vote_views.vote_page, name='vote_page'),
    path('vote/<uuid:vote_uuid>/submit/', callbacks_vote_views.submit_vote, name='submit_vote'),
    path('vote/<uuid:vote_uuid>/thanks/', callbacks_vote_views.vote_thanks, name='vote_thanks'),

]
