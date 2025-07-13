# teams/models.py
from django.db import models
from django.conf import settings


class Region(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название региона")
    code = models.CharField(max_length=20, unique=True, verbose_name="Код региона")
    description = models.TextField(blank=True, verbose_name="Описание")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        verbose_name="Создал"
    )

    class Meta:
        ordering = ['name']
        verbose_name = "Регион"
        verbose_name_plural = "Регионы"

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def team_count(self):
        return self.teams.filter(is_active=True).count()

    @property
    def total_team_count(self):
        return self.teams.count()


class Team(models.Model):
    name = models.CharField(max_length=100, verbose_name="Название бригады")
    description = models.TextField(blank=True, verbose_name="Описание")
    region = models.ForeignKey(
        Region, 
        on_delete=models.CASCADE, 
        related_name='teams',
        verbose_name="Регион"
    )
    is_active = models.BooleanField(default=True, verbose_name="Активна")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создана")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        verbose_name="Создал"
    )

    class Meta:
        ordering = ['region__name', 'name']
        verbose_name = "Бригада"
        verbose_name_plural = "Бригады"
        unique_together = ['name', 'region']

    def __str__(self):
        return f"{self.name} - {self.region.name} (ID: {self.id})"