# teams/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Avg, Case, When, IntegerField
from django.utils import timezone
from datetime import datetime, timedelta
from .models import Team
from .forms import TeamForm


@login_required
def team_list(request):
    search = request.GET.get('search', '')
    show_inactive = request.GET.get('show_inactive', False)

    # Base queryset with statistics
    teams = Team.objects.annotate(
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
        teams = teams.filter(Q(name__icontains=search) | Q(description__icontains=search))

    teams = teams.order_by('name')

    # Calculate summary statistics
    total_teams = teams.count()
    active_teams = teams.filter(is_active=True).count()
    total_callbacks = sum(team.callback_count or 0 for team in teams)

    context = {
        'teams': teams,
        'search': search,
        'show_inactive': show_inactive,
        'total_teams': total_teams,
        'active_teams': active_teams,
        'total_callbacks': total_callbacks,
    }

    return render(request, 'teams/list.html', context)


@login_required
def team_detail(request, pk):
    team = get_object_or_404(Team, pk=pk)

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
    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save(commit=False)
            team.created_by = request.user
            team.save()
            messages.success(request, f'Team "{team.name}" created successfully!')
            return redirect('teams:detail', pk=team.pk)
    else:
        form = TeamForm()

    # Quick statistics for the form page
    team_count = Team.objects.filter(is_active=True).count()
    total_callbacks = Team.objects.filter(is_active=True).annotate(
        callback_count=Count('callbackrequest')
    ).aggregate(total=Count('callbackrequest'))['total'] or 0

    context = {
        'form': form,
        'title': 'Create Emergency Team',
        'team_count': team_count,
        'total_callbacks': total_callbacks,
    }

    return render(request, 'teams/form.html', context)


@login_required
def team_edit(request, pk):
    team = get_object_or_404(Team, pk=pk)

    if request.method == 'POST':
        form = TeamForm(request.POST, instance=team)
        if form.is_valid():
            # Handle is_active field manually since it's not in the form
            if 'is_active' in request.POST:
                team.is_active = request.POST.get('is_active') == 'on'

            form.save()
            messages.success(request, f'Team "{team.name}" updated successfully!')
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
        'title': 'Edit Emergency Team',
        'team': team,
        'callback_count': callback_count,
        'rating_count': rating_count,
        'avg_rating': round(avg_rating, 1),
    }

    return render(request, 'teams/form.html', context)


@login_required
def team_delete(request, pk):
    team = get_object_or_404(Team, pk=pk)

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
            messages.success(request, f'Team "{team.name}" has been deactivated successfully!')
            return redirect('teams:list')
        elif action == 'delete' and request.user.is_staff:
            team_name = team.name
            team.delete()
            messages.warning(request, f'Team "{team_name}" has been permanently deleted!')
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