# teams/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Avg, Case, When, IntegerField
from django.utils import timezone
from django.http import JsonResponse
from datetime import datetime, timedelta
from .models import Team, Region
from .forms import TeamForm, RegionForm, TeamSearchForm, RegionSearchForm


# REGION VIEWS

@login_required
def region_list(request):
    search = request.GET.get('search', '')
    show_inactive = request.GET.get('show_inactive', False)
    sort_by = request.GET.get('sort_by', 'name')

    # Base queryset with statistics
    regions = Region.objects.annotate(
        active_teams_count=Count('teams', filter=Q(teams__is_active=True)),
        total_teams_count=Count('teams'),
        total_callbacks_count=Count('teams__callbackrequest')
    )

    # Filter by active status
    if not show_inactive:
        regions = regions.filter(is_active=True)

    # Search filter
    if search:
        regions = regions.filter(
            Q(name__icontains=search) |
            Q(code__icontains=search) |
            Q(description__icontains=search)
        )

    # Apply sorting
    if sort_by == '-team_count':
        regions = regions.order_by('-active_teams_count')
    elif sort_by in ['name', '-name', 'code', '-code', 'created_at', '-created_at']:
        regions = regions.order_by(sort_by)
    else:
        regions = regions.order_by('name')

    # Calculate summary statistics
    total_regions = regions.count()
    active_regions = regions.filter(is_active=True).count()
    total_teams_in_regions = sum(region.active_teams_count or 0 for region in regions)

    context = {
        'regions': regions,
        'search': search,
        'show_inactive': show_inactive,
        'sort_by': sort_by,
        'total_regions': total_regions,
        'active_regions': active_regions,
        'total_teams': total_teams_in_regions,
    }

    return render(request, 'teams/regions/list.html', context)


@login_required
def region_detail(request, pk):
    region = get_object_or_404(Region, pk=pk)

    # Import here to avoid circular imports
    from callbacks.models import CallbackRequest, Rating, CallStatus

    # Get region teams and statistics
    teams = region.teams.annotate(
        callback_count=Count('callbackrequest'),
        completed_count=Count('callbackrequest', filter=Q(callbackrequest__status=CallStatus.COMPLETED)),
        rating_count=Count('callbackrequest__rating'),
        avg_rating=Avg('callbackrequest__rating__rating')
    )

    active_teams = teams.filter(is_active=True)
    total_teams = teams.count()

    # Callback statistics for the region
    total_callbacks = sum(team.callback_count or 0 for team in teams)
    completed_callbacks = sum(team.completed_count or 0 for team in teams)

    # Recent teams (last 5 created)
    recent_teams = teams.order_by('-created_at')[:5]

    # Success rate
    success_rate = 0
    if total_callbacks > 0:
        success_rate = round((completed_callbacks / total_callbacks) * 100, 1)

    context = {
        'region': region,
        'teams': active_teams,
        'total_teams': total_teams,
        'active_teams': active_teams.count(),
        'total_callbacks': total_callbacks,
        'completed_callbacks': completed_callbacks,
        'success_rate': success_rate,
        'recent_teams': recent_teams,
    }

    return render(request, 'teams/regions/detail.html', context)


@login_required
def region_create(request):
    if request.method == 'POST':
        form = RegionForm(request.POST)
        if form.is_valid():
            region = form.save(commit=False)
            region.created_by = request.user
            region.save()
            messages.success(request, f'Регион "{region.name}" успешно создан!')
            return redirect('teams:region_detail', pk=region.pk)
    else:
        form = RegionForm()

    # Quick statistics for the form page
    region_count = Region.objects.filter(is_active=True).count()
    total_teams = Team.objects.filter(is_active=True).count()

    context = {
        'form': form,
        'title': 'Создать новый регион',
        'region_count': region_count,
        'total_teams': total_teams,
    }

    return render(request, 'teams/regions/form.html', context)


@login_required
def region_edit(request, pk):
    region = get_object_or_404(Region, pk=pk)

    if request.method == 'POST':
        form = RegionForm(request.POST, instance=region)
        if form.is_valid():
            # Handle is_active field manually since it's not in the form
            if 'is_active' in request.POST:
                region.is_active = request.POST.get('is_active') == 'on'

            form.save()
            messages.success(request, f'Регион "{region.name}" успешно обновлен!')
            return redirect('teams:region_detail', pk=region.pk)
    else:
        form = RegionForm(instance=region)

    # Get region statistics for the edit page
    team_count = region.teams.count()
    active_team_count = region.teams.filter(is_active=True).count()

    context = {
        'form': form,
        'title': 'Редактировать регион',
        'region': region,
        'team_count': team_count,
        'active_team_count': active_team_count,
    }

    return render(request, 'teams/regions/form.html', context)


@login_required
def region_delete(request, pk):
    region = get_object_or_404(Region, pk=pk)

    # Get impact information
    team_count = region.teams.count()
    active_team_count = region.teams.filter(is_active=True).count()

    # Import here to avoid circular imports
    from callbacks.models import CallbackRequest

    total_callbacks = CallbackRequest.objects.filter(team__region=region).count()
    recent_callbacks = CallbackRequest.objects.filter(
        team__region=region,
        created_at__gte=timezone.now() - timedelta(days=30)
    ).count()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'deactivate':
            region.is_active = False
            region.save()
            messages.success(request, f'Регион "{region.name}" был успешно деактивирован!')
            return redirect('teams:region_list')
        elif action == 'delete' and request.user.is_staff:
            region_name = region.name
            region.delete()
            messages.warning(request, f'Регион "{region_name}" был окончательно удален!')
            return redirect('teams:region_list')

    context = {
        'region': region,
        'team_count': team_count,
        'active_team_count': active_team_count,
        'total_callbacks': total_callbacks,
        'recent_callbacks': recent_callbacks,
    }

    return render(request, 'teams/regions/delete.html', context)


# UPDATED TEAM VIEWS

@login_required
def team_list(request):
    search = request.GET.get('search', '')
    region_id = request.GET.get('region', '')
    show_inactive = request.GET.get('show_inactive', False)
    sort_by = request.GET.get('sort_by', 'region__name')

    # Base queryset with statistics
    teams = Team.objects.select_related('region', 'created_by').annotate(
        callback_count=Count('callbackrequest'),
        completed_count=Count('callbackrequest', filter=Q(callbackrequest__status='completed')),
        rating_count=Count('callbackrequest__rating'),
        avg_rating=Avg('callbackrequest__rating__rating')
    )

    # Filter by active status
    if not show_inactive:
        teams = teams.filter(is_active=True)

    # Search filter
    if search:
        teams = teams.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search) |
            Q(region__name__icontains=search)
        )

    # Region filter
    if region_id:
        teams = teams.filter(region_id=region_id)

    # Apply sorting
    if sort_by in ['name', '-name', 'region__name', '-region__name', 'created_at', '-created_at', '-callback_count',
                   '-avg_rating']:
        teams = teams.order_by(sort_by, 'name')
    else:
        teams = teams.order_by('region__name', 'name')

    # Calculate summary statistics
    total_teams = teams.count()
    active_teams = teams.filter(is_active=True).count()
    total_callbacks = sum(team.callback_count or 0 for team in teams)

    # Get regions for filter
    regions = Region.objects.filter(is_active=True).order_by('name')

    context = {
        'teams': teams,
        'regions': regions,
        'search': search,
        'selected_region': region_id,
        'show_inactive': show_inactive,
        'sort_by': sort_by,
        'total_teams': total_teams,
        'active_teams': active_teams,
        'total_callbacks': total_callbacks,
    }

    return render(request, 'teams/list.html', context)


@login_required
def team_detail(request, pk):
    team = get_object_or_404(Team.objects.select_related('region', 'created_by'), pk=pk)

    # Import here to avoid circular imports
    from callbacks.models import CallbackRequest, Rating, CallStatus

    # Get team statistics
    callbacks = CallbackRequest.objects.filter(team=team)

    # Basic counts
    total_callbacks = callbacks.count()
    completed_callbacks = callbacks.filter(status=CallStatus.COMPLETED).count()
    failed_callbacks = callbacks.filter(status=CallStatus.FAILED).count()
    pending_callbacks = callbacks.filter(
        status__in=[CallStatus.PENDING, CallStatus.DIALING, CallStatus.CONNECTING]
    ).count()

    # Rating statistics
    ratings = Rating.objects.filter(team=team)
    total_ratings = ratings.count()
    avg_rating = ratings.aggregate(Avg('rating'))['rating__avg'] or 0

    # Rating distribution
    rating_distribution = []
    for i in range(1, 6):
        count = ratings.filter(rating=i).count()
        percentage = (count / total_ratings * 100) if total_ratings > 0 else 0
        rating_distribution.append({
            'rating': i,
            'count': count,
            'percentage': round(percentage, 1)
        })

    # Success rate
    success_rate = 0
    if total_callbacks > 0:
        success_rate = round((completed_callbacks / total_callbacks) * 100, 1)

    # Recent activity (last 10 callbacks)
    recent_callbacks = callbacks.select_related('requested_by').order_by('-created_at')[:10]

    # Time-based statistics
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    today_callbacks = callbacks.filter(created_at__date=today).count()
    week_callbacks = callbacks.filter(created_at__date__gte=week_ago).count()
    month_callbacks = callbacks.filter(created_at__date__gte=month_ago).count()

    # Good ratings (4+ stars)
    good_ratings = ratings.filter(rating__gte=4).count()
    good_rating_percentage = (good_ratings / total_ratings * 100) if total_ratings > 0 else 0

    context = {
        'team': team,
        'total_callbacks': total_callbacks,
        'completed_callbacks': completed_callbacks,
        'failed_callbacks': failed_callbacks,
        'pending_callbacks': pending_callbacks,
        'total_ratings': total_ratings,
        'avg_rating': round(avg_rating, 1),
        'rating_distribution': rating_distribution,
        'success_rate': success_rate,
        'recent_callbacks': recent_callbacks,
        'today_callbacks': today_callbacks,
        'week_callbacks': week_callbacks,
        'month_callbacks': month_callbacks,
        'good_rating_percentage': round(good_rating_percentage, 1),
    }

    return render(request, 'teams/detail.html', context)


@login_required
def team_create(request):
    # Check if there are any active regions first
    if not Region.objects.filter(is_active=True).exists():
        messages.error(request, 'Перед созданием бригады необходимо создать хотя бы один регион.')
        return redirect('teams:region_create')

    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save(commit=False)
            team.created_by = request.user
            team.save()
            messages.success(request, f'Бригада "{team.name}" успешно создана!')
            return redirect('teams:detail', pk=team.pk)
    else:
        form = TeamForm()

    # Quick statistics for the form page
    team_count = Team.objects.filter(is_active=True).count()
    region_count = Region.objects.filter(is_active=True).count()
    total_callbacks = Team.objects.filter(is_active=True).annotate(
        callback_count=Count('callbackrequest')
    ).aggregate(total=Count('callbackrequest'))['total'] or 0

    context = {
        'form': form,
        'title': 'Создать экстренную бригаду',
        'team_count': team_count,
        'region_count': region_count,
        'total_callbacks': total_callbacks,
    }

    return render(request, 'teams/form.html', context)


@login_required
def team_edit(request, pk):
    team = get_object_or_404(Team.objects.select_related('region'), pk=pk)

    if request.method == 'POST':
        form = TeamForm(request.POST, instance=team)
        if form.is_valid():
            # Handle is_active field manually since it's not in the form
            if 'is_active' in request.POST:
                team.is_active = request.POST.get('is_active') == 'on'

            form.save()
            messages.success(request, f'Бригада "{team.name}" успешно обновлена!')
            return redirect('teams:detail', pk=team.pk)
    else:
        form = TeamForm(instance=team)

    # Get team statistics for the edit page
    from callbacks.models import CallbackRequest, Rating

    callback_count = CallbackRequest.objects.filter(team=team).count()
    rating_count = Rating.objects.filter(team=team).count()
    avg_rating = Rating.objects.filter(team=team).aggregate(Avg('rating'))['rating__avg'] or 0

    context = {
        'form': form,
        'title': 'Редактировать экстренную бригаду',
        'team': team,
        'callback_count': callback_count,
        'rating_count': rating_count,
        'avg_rating': round(avg_rating, 1),
    }

    return render(request, 'teams/form.html', context)


@login_required
def team_delete(request, pk):
    team = get_object_or_404(Team.objects.select_related('region'), pk=pk)

    # Import here to avoid circular imports
    from callbacks.models import CallbackRequest, Rating

    # Get impact information
    callback_count = CallbackRequest.objects.filter(team=team).count()
    rating_count = Rating.objects.filter(team=team).count()
    recent_callbacks = CallbackRequest.objects.filter(
        team=team,
        created_at__gte=timezone.now() - timedelta(days=30)
    ).count()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'deactivate':
            team.is_active = False
            team.save()
            messages.success(request, f'Бригада "{team.name}" была успешно деактивирована!')
            return redirect('teams:list')
        elif action == 'delete' and request.user.is_staff:
            team_name = team.name
            team.delete()
            messages.warning(request, f'Бригада "{team_name}" была окончательно удалена!')
            return redirect('teams:list')

    context = {
        'team': team,
        'callback_count': callback_count,
        'rating_count': rating_count,
        'recent_callbacks': recent_callbacks,
    }

    return render(request, 'teams/delete.html', context)


@login_required
def team_stats_api(request, pk):
    """API endpoint for team statistics (for AJAX calls)"""
    team = get_object_or_404(Team, pk=pk)

    from callbacks.models import CallbackRequest, Rating
    from django.http import JsonResponse

    # Calculate statistics
    callbacks = CallbackRequest.objects.filter(team=team)
    ratings = Rating.objects.filter(team=team)

    stats = {
        'total_callbacks': callbacks.count(),
        'completed_callbacks': callbacks.filter(status='completed').count(),
        'total_ratings': ratings.count(),
        'avg_rating': round(ratings.aggregate(Avg('rating'))['rating__avg'] or 0, 1),
        'rating_distribution': [],
    }

    # Rating distribution
    for i in range(1, 6):
        count = ratings.filter(rating=i).count()
        percentage = (count / stats['total_ratings'] * 100) if stats['total_ratings'] > 0 else 0
        stats['rating_distribution'].append({
            'rating': i,
            'count': count,
            'percentage': round(percentage, 1)
        })

    return JsonResponse(stats)