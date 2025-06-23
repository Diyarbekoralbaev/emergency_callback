# callbacks/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count, Avg, Q
from django.utils import timezone
from datetime import datetime, timedelta
from .models import CallbackRequest, Rating, CallStatus
from .forms import CallbackRequestForm
from .tasks import fixed_process_callback_call as process_callback_call
from teams.models import Team


@login_required
def dashboard(request):
    # Today's stats
    today = timezone.now().date()

    # Call stats
    total_calls_today = CallbackRequest.objects.filter(created_at__date=today).count()
    completed_calls_today = CallbackRequest.objects.filter(
        created_at__date=today,
        status__in=[CallStatus.COMPLETED, CallStatus.TRANSFERRED]
    ).count()
    failed_calls_today = CallbackRequest.objects.filter(
        created_at__date=today,
        status=CallStatus.FAILED
    ).count()
    pending_calls_today = CallbackRequest.objects.filter(
        created_at__date=today,
        status__in=[CallStatus.PENDING, CallStatus.DIALING, CallStatus.CONNECTING]
    ).count()

    # Rating stats
    ratings_today = Rating.objects.filter(date=today)
    total_ratings_today = ratings_today.count()
    avg_rating_today = ratings_today.aggregate(Avg('rating'))['rating__avg'] or 0

    # Fixed rating distribution - ensure all ratings 1-5 are shown
    rating_distribution = []
    for i in range(1, 6):
        count = ratings_today.filter(rating=i).count()
        percentage = (count / total_ratings_today * 100) if total_ratings_today > 0 else 0
        rating_distribution.append({
            'rating': i,
            'count': count,
            'percentage': round(percentage, 1)
        })

    # Success rate calculation
    success_rate = 0
    if total_calls_today > 0:
        success_rate = round((completed_calls_today / total_calls_today) * 100, 1)

    # Recent calls with ratings info
    recent_calls = CallbackRequest.objects.select_related('team', 'requested_by').prefetch_related('rating').order_by(
        '-created_at')[:10]

    context = {
        'total_calls_today': total_calls_today,
        'completed_calls_today': completed_calls_today,
        'failed_calls_today': failed_calls_today,
        'pending_calls_today': pending_calls_today,
        'total_ratings_today': total_ratings_today,
        'avg_rating_today': round(avg_rating_today, 1),
        'success_rate': success_rate,
        'rating_distribution': rating_distribution,
        'recent_calls': recent_calls,
    }

    return render(request, 'callbacks/dashboard.html', context)


@login_required
def callback_list(request):
    status_filter = request.GET.get('status', '')
    team_filter = request.GET.get('team', '')
    search = request.GET.get('search', '')

    callbacks = CallbackRequest.objects.select_related('team', 'requested_by').order_by('-created_at')

    if status_filter:
        callbacks = callbacks.filter(status=status_filter)

    # Fixed team filter bug
    if team_filter:
        callbacks = callbacks.filter(team_id=team_filter)

    if search:
        callbacks = callbacks.filter(
            Q(phone_number__icontains=search) |
            Q(team__name__icontains=search)
        )

    # For filters
    teams = Team.objects.filter(is_active=True)
    statuses = CallStatus.choices

    # Pagination-like limit
    total_count = callbacks.count()
    callbacks = callbacks[:50]  # Limit to 50 for performance

    context = {
        'callbacks': callbacks,
        'teams': teams,
        'statuses': statuses,
        'current_status': status_filter,
        'current_team': team_filter,
        'search': search,
        'total_count': total_count,
        'showing_count': len(callbacks),
    }

    return render(request, 'callbacks/list.html', context)


@login_required
def callback_create(request):
    if request.method == 'POST':
        form = CallbackRequestForm(request.POST)
        if form.is_valid():
            callback = form.save(commit=False)
            callback.requested_by = request.user
            callback.save()

            # Process call asynchronously
            process_callback_call.delay(callback.id)

            messages.success(request, f'Callback request created! Calling {callback.phone_number}...')
            return redirect('callbacks:list')
    else:
        form = CallbackRequestForm()

    # Quick stats for the form page
    today = timezone.now().date()
    today_calls = CallbackRequest.objects.filter(created_at__date=today).count()
    today_completed = CallbackRequest.objects.filter(created_at__date=today, status=CallStatus.COMPLETED).count()
    today_ratings = Rating.objects.filter(date=today).count()

    # Calculate success rate for the form page
    today_success_rate = 0
    if today_calls > 0:
        today_success_rate = round((today_completed / today_calls) * 100, 0)

    context = {
        'form': form,
        'title': 'Create Callback Request',
        'today_calls': today_calls,
        'today_completed': today_completed,
        'today_ratings': today_ratings,
        'today_success_rate': today_success_rate,
    }

    return render(request, 'callbacks/form.html', context)


@login_required
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


@login_required
def ratings_list(request):
    team_filter = request.GET.get('team', '')
    rating_filter = request.GET.get('rating', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    ratings = Rating.objects.select_related('team', 'callback_request').order_by('-timestamp')

    # Fixed team filter bug
    if team_filter:
        ratings = ratings.filter(team_id=team_filter)

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
    teams = Team.objects.filter(is_active=True)

    # Limit for performance
    ratings_list = ratings[:100]

    context = {
        'ratings': ratings_list,
        'teams': teams,
        'current_team': team_filter,
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