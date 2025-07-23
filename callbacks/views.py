import json
import random

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count, Avg, Q
from django.utils import timezone
from datetime import datetime, timedelta

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import CallbackRequest, Rating, CallStatus
from .forms import CallbackRequestForm
from .tasks import fixed_process_callback_call as process_callback_call
from teams.models import Team, Region
from teams.permissions import admin_required, has_role
from users.models import UserRoleChoices


@admin_required
def dashboard(request):
    # Get filter parameters
    region_filter = request.GET.get('region', '')
    team_filter = request.GET.get('team', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    status_filter = request.GET.get('status', '')

    # Default date range (today if no filters)
    if not date_from and not date_to:
        today = timezone.now().date()
        date_from = today
        date_to = today
    else:
        if date_from:
            date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
        else:
            date_from = timezone.now().date() - timedelta(days=30)  # Default to last 30 days

        if date_to:
            date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
        else:
            date_to = timezone.now().date()

    # Base querysets with date filtering
    callbacks_qs = CallbackRequest.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to
    )

    ratings_qs = Rating.objects.filter(
        date__gte=date_from,
        date__lte=date_to
    )

    # Apply region filter
    if region_filter:
        callbacks_qs = callbacks_qs.filter(team__region_id=region_filter)
        ratings_qs = ratings_qs.filter(team__region_id=region_filter)

    # Apply team filter
    if team_filter:
        callbacks_qs = callbacks_qs.filter(team_id=team_filter)
        ratings_qs = ratings_qs.filter(team_id=team_filter)

    # Apply status filter
    if status_filter:
        callbacks_qs = callbacks_qs.filter(status=status_filter)

    # Call statistics
    total_calls = callbacks_qs.count()
    completed_calls = callbacks_qs.filter(
        status__in=[CallStatus.COMPLETED, CallStatus.TRANSFERRED]
    ).count()
    failed_calls = callbacks_qs.filter(status=CallStatus.FAILED).count()
    pending_calls = callbacks_qs.filter(
        status__in=[CallStatus.PENDING, CallStatus.DIALING, CallStatus.CONNECTING]
    ).count()

    # Rating statistics
    total_ratings = ratings_qs.count()
    avg_rating = ratings_qs.aggregate(Avg('rating'))['rating__avg'] or 0

    # Rating distribution - ensure all ratings 1-5 are shown
    rating_distribution = []
    for i in range(1, 6):
        count = ratings_qs.filter(rating=i).count()
        percentage = (count / total_ratings * 100) if total_ratings > 0 else 0
        rating_distribution.append({
            'rating': i,
            'count': count,
            'percentage': round(percentage, 1)
        })

    # Success rate calculation
    success_rate = 0
    if total_calls > 0:
        success_rate = round((completed_calls / total_calls) * 100, 1)

    # Recent calls with ratings info (respecting filters)
    recent_calls_qs = callbacks_qs.select_related('team', 'team__region', 'requested_by').prefetch_related('rating')
    recent_calls = recent_calls_qs.order_by('-created_at')[:15]

    # Additional statistics for filtered period
    # Daily breakdown for chart (last 7 days within filter range)
    daily_stats = []
    chart_start_date = max(date_from, timezone.now().date() - timedelta(days=6))
    chart_end_date = min(date_to, timezone.now().date())

    current_date = chart_start_date
    while current_date <= chart_end_date:
        day_calls = callbacks_qs.filter(created_at__date=current_date)
        day_completed = day_calls.filter(status__in=[CallStatus.COMPLETED, CallStatus.TRANSFERRED]).count()
        day_total = day_calls.count()
        day_success_rate = (day_completed / day_total * 100) if day_total > 0 else 0

        daily_stats.append({
            'date': current_date.strftime('%m-%d'),
            'total_calls': day_total,
            'completed_calls': day_completed,
            'success_rate': round(day_success_rate, 1)
        })
        current_date += timedelta(days=1)

    # Team performance breakdown
    team_stats = []
    if region_filter or team_filter:
        # Show individual team stats when filtered
        teams_qs = Team.objects.filter(is_active=True)
        if region_filter:
            teams_qs = teams_qs.filter(region_id=region_filter)
        if team_filter:
            teams_qs = teams_qs.filter(id=team_filter)

        for team in teams_qs[:10]:  # Limit to top 10 teams
            team_calls = callbacks_qs.filter(team=team)
            team_total = team_calls.count()
            team_completed = team_calls.filter(status__in=[CallStatus.COMPLETED, CallStatus.TRANSFERRED]).count()
            team_ratings = ratings_qs.filter(team=team)
            team_avg_rating = team_ratings.aggregate(Avg('rating'))['rating__avg'] or 0

            if team_total > 0:  # Only show teams with calls
                team_stats.append({
                    'team': team,
                    'total_calls': team_total,
                    'completed_calls': team_completed,
                    'success_rate': round((team_completed / team_total * 100), 1),
                    'avg_rating': round(team_avg_rating, 1),
                    'total_ratings': team_ratings.count()
                })
    else:
        # Show region stats when no specific filter
        for region in Region.objects.filter(is_active=True)[:5]:
            region_calls = callbacks_qs.filter(team__region=region)
            region_total = region_calls.count()
            region_completed = region_calls.filter(status__in=[CallStatus.COMPLETED, CallStatus.TRANSFERRED]).count()
            region_ratings = ratings_qs.filter(team__region=region)
            region_avg_rating = region_ratings.aggregate(Avg('rating'))['rating__avg'] or 0

            if region_total > 0:  # Only show regions with calls
                team_stats.append({
                    'team': region,  # Using same template structure
                    'total_calls': region_total,
                    'completed_calls': region_completed,
                    'success_rate': round((region_completed / region_total * 100), 1),
                    'avg_rating': round(region_avg_rating, 1),
                    'total_ratings': region_ratings.count()
                })

    # Sort team stats by total calls
    team_stats.sort(key=lambda x: x['total_calls'], reverse=True)

    # For filter dropdowns
    regions = Region.objects.filter(is_active=True).order_by('name')
    teams = Team.objects.filter(is_active=True).select_related('region').order_by('region__name', 'name')
    if region_filter:
        teams = teams.filter(region_id=region_filter)

    # Calculate period description for display
    if date_from == date_to:
        if date_from == timezone.now().date():
            period_description = "Сегодня"
        else:
            period_description = f"За {date_from.strftime('%d.%m.%Y')}"
    else:
        period_description = f"С {date_from.strftime('%d.%m.%Y')} по {date_to.strftime('%d.%m.%Y')}"

    context = {
        'total_calls': total_calls,
        'completed_calls': completed_calls,
        'failed_calls': failed_calls,
        'pending_calls': pending_calls,
        'total_ratings': total_ratings,
        'avg_rating': round(avg_rating, 1),
        'success_rate': success_rate,
        'rating_distribution': rating_distribution,
        'recent_calls': recent_calls,
        'daily_stats': daily_stats,
        'team_stats': team_stats,

        # Filter data
        'regions': regions,
        'teams': teams,
        'statuses': CallStatus.choices,
        'current_region': region_filter,
        'current_team': team_filter,
        'current_status': status_filter,
        'date_from': date_from.strftime('%Y-%m-%d'),
        'date_to': date_to.strftime('%Y-%m-%d'),
        'period_description': period_description,

        # Additional context
        'has_filters': bool(region_filter or team_filter or status_filter or
                            request.GET.get('date_from') or request.GET.get('date_to')),
        'filter_count': sum([bool(region_filter), bool(team_filter), bool(status_filter),
                             bool(request.GET.get('date_from')), bool(request.GET.get('date_to'))]),
    }

    return render(request, 'callbacks/dashboard.html', context)


@has_role([UserRoleChoices.ADMIN, UserRoleChoices.OPERATOR])
def callback_list(request):
    status_filter = request.GET.get('status', '')
    team_filter = request.GET.get('team', '')
    region_filter = request.GET.get('region', '')
    search = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    callbacks = CallbackRequest.objects.select_related('team', 'team__region', 'requested_by').order_by('-created_at')

    # Apply filters
    if status_filter:
        callbacks = callbacks.filter(status=status_filter)

    if team_filter:
        callbacks = callbacks.filter(team_id=team_filter)

    if region_filter:
        callbacks = callbacks.filter(team__region_id=region_filter)

    if search:
        callbacks = callbacks.filter(
            Q(phone_number__icontains=search) |
            Q(team__name__icontains=search) |
            Q(team__region__name__icontains=search)
        )

    if date_from:
        callbacks = callbacks.filter(created_at__date__gte=date_from)

    if date_to:
        callbacks = callbacks.filter(created_at__date__lte=date_to)

    # For filters
    regions = Region.objects.filter(is_active=True).order_by('name')
    teams = Team.objects.filter(is_active=True).select_related('region').order_by('region__name', 'name')
    if region_filter:
        teams = teams.filter(region_id=region_filter)
    statuses = CallStatus.choices

    # Pagination-like limit
    total_count = callbacks.count()
    callbacks = callbacks[:100]  # Increased limit

    context = {
        'callbacks': callbacks,
        'regions': regions,
        'teams': teams,
        'statuses': statuses,
        'current_status': status_filter,
        'current_team': team_filter,
        'current_region': region_filter,
        'search': search,
        'date_from': date_from,
        'date_to': date_to,
        'total_count': total_count,
        'showing_count': len(callbacks),
    }

    return render(request, 'callbacks/list.html', context)


@has_role([UserRoleChoices.ADMIN, UserRoleChoices.OPERATOR])
def callback_create(request):
    if request.method == 'POST':
        form = CallbackRequestForm(request.POST)
        if form.is_valid():
            callback = form.save(commit=False)
            callback.requested_by = request.user
            callback.save()

            # Process call asynchronously
            process_callback_call.delay(callback.id)

            messages.success(request, f'Экстренный вызов создан! Звоним на номер {callback.phone_number}...')
            return redirect('callbacks:list')
    else:
        form = CallbackRequestForm()

    # Quick stats for the form page (today only)
    today = timezone.now().date()
    today_calls = CallbackRequest.objects.filter(created_at__date=today).count()
    today_completed = CallbackRequest.objects.filter(
        created_at__date=today,
        status__in=[CallStatus.COMPLETED, CallStatus.TRANSFERRED]
    ).count()
    today_ratings = Rating.objects.filter(date=today).count()

    # Calculate success rate for the form page
    today_success_rate = 0
    if today_calls > 0:
        today_success_rate = round((today_completed / today_calls) * 100, 0)

    # Get regions and teams for the enhanced form
    regions = Region.objects.filter(is_active=True).order_by('name')
    teams = Team.objects.filter(is_active=True).select_related('region').order_by('region__name', 'name')

    context = {
        'form': form,
        'title': 'Создать экстренный вызов',
        'today_calls': today_calls,
        'today_completed': today_completed,
        'today_ratings': today_ratings,
        'today_success_rate': today_success_rate,
        'regions': regions,
        'teams': teams,
    }

    return render(request, 'callbacks/form.html', context)


@has_role([UserRoleChoices.ADMIN, UserRoleChoices.OPERATOR])
def callback_detail(request, pk):
    callback = get_object_or_404(CallbackRequest, pk=pk)

    # Get rating if exists
    rating = None
    try:
        rating = callback.rating
    except:
        pass

    context = {
        'callback': callback,
        'rating': rating,
    }

    return render(request, 'callbacks/detail.html', context)


@admin_required
def ratings_list(request):
    team_filter = request.GET.get('team', '')
    region_filter = request.GET.get('region', '')
    rating_filter = request.GET.get('rating', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    ratings = Rating.objects.select_related('team', 'team__region', 'callback_request').order_by('-timestamp')

    # Apply filters
    if team_filter:
        ratings = ratings.filter(team_id=team_filter)

    if region_filter:
        ratings = ratings.filter(team__region_id=region_filter)

    if rating_filter:
        ratings = ratings.filter(rating=rating_filter)

    if date_from:
        ratings = ratings.filter(date__gte=date_from)

    if date_to:
        ratings = ratings.filter(date__lte=date_to)

    # Calculate statistics for filtered ratings
    total_ratings = ratings.count()
    avg_rating = ratings.aggregate(Avg('rating'))['rating__avg'] or 0

    # Rating distribution for filtered results
    rating_stats = {}
    for i in range(1, 6):
        count = ratings.filter(rating=i).count()
        percentage = (count / total_ratings * 100) if total_ratings > 0 else 0
        rating_stats[i] = {
            'count': count,
            'percentage': round(percentage, 1)
        }

    # Good ratings (4+ stars)
    good_ratings = ratings.filter(rating__gte=4).count()
    good_percentage = (good_ratings / total_ratings * 100) if total_ratings > 0 else 0

    # For filters
    regions = Region.objects.filter(is_active=True).order_by('name')
    teams = Team.objects.filter(is_active=True).select_related('region').order_by('region__name', 'name')
    if region_filter:
        teams = teams.filter(region_id=region_filter)

    # Limit for performance
    ratings_list = ratings[:100]

    context = {
        'ratings': ratings_list,
        'regions': regions,
        'teams': teams,
        'current_team': team_filter,
        'current_region': region_filter,
        'current_rating': rating_filter,
        'date_from': date_from,
        'date_to': date_to,
        'total_ratings': total_ratings,
        'avg_rating': round(avg_rating, 1),
        'rating_stats': rating_stats,
        'good_percentage': round(good_percentage, 1),
        'showing_count': len(ratings_list),
    }

    return render(request, 'callbacks/ratings.html', context)


# AJAX endpoint for getting teams by region
@has_role([UserRoleChoices.ADMIN, UserRoleChoices.OPERATOR])
def get_teams_by_region(request):
    region_id = request.GET.get('region_id')
    teams = []

    if region_id:
        teams_qs = Team.objects.filter(region_id=region_id, is_active=True).order_by('name')
        teams = [{'id': team.id, 'name': team.name} for team in teams_qs]

    return JsonResponse({'teams': teams})


@csrf_exempt
@require_http_methods(["POST"])
def api_callback_create(request):
    try:
        # Parse JSON data
        data = json.loads(request.body)
        phone_number = data.get('phone_number')

        if not phone_number:
            return JsonResponse({'error': 'phone_number is required'}, status=400)

        # Get first user for requested_by
        from users.models import User
        user = User.objects.first()
        if not user:
            return JsonResponse({'error': 'No users found'}, status=500)

        # Get random active team
        teams = list(Team.objects.filter(is_active=True))
        if not teams:
            return JsonResponse({'error': 'No active teams found'}, status=500)

        team = random.choice(teams)

        # Create callback request
        callback = CallbackRequest.objects.create(
            phone_number=phone_number,
            team=team,
            requested_by=user
        )

        # Process call asynchronously
        process_callback_call.delay(callback.id)

        return JsonResponse({
            'success': True,
            'callback_id': callback.id,
            'phone_number': callback.phone_number,
            'team': callback.team.name,
            'region': callback.team.region.name if hasattr(callback.team, 'region') and callback.team.region else None,
            'status': callback.status
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)