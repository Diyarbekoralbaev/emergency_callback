from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from .models import Team
from .forms import TeamForm


@login_required
def team_list(request):
    search = request.GET.get('search', '')
    teams = Team.objects.filter(is_active=True)

    if search:
        teams = teams.filter(Q(name__icontains=search))

    return render(request, 'teams/list.html', {'teams': teams, 'search': search})


@login_required
def team_create(request):
    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save(commit=False)
            team.created_by = request.user
            team.save()
            messages.success(request, 'Team created successfully!')
            return redirect('teams:list')
    else:
        form = TeamForm()

    return render(request, 'teams/form.html', {'form': form, 'title': 'Create Team'})


@login_required
def team_edit(request, pk):
    team = get_object_or_404(Team, pk=pk)

    if request.method == 'POST':
        form = TeamForm(request.POST, instance=team)
        if form.is_valid():
            form.save()
            messages.success(request, 'Team updated successfully!')
            return redirect('teams:list')
    else:
        form = TeamForm(instance=team)

    return render(request, 'teams/form.html', {'form': form, 'title': 'Edit Team', 'team': team})


@login_required
def team_delete(request, pk):
    team = get_object_or_404(Team, pk=pk)

    if request.method == 'POST':
        team.is_active = False
        team.save()
        messages.success(request, 'Team deactivated successfully!')
        return redirect('teams:list')

    return render(request, 'teams/delete.html', {'team': team})
