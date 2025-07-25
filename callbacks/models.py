# callbacks/models.py
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from users.models import User
from teams.models import Team
import uuid
import re


class CallStatus(models.TextChoices):
    PENDING = 'pending', 'В ожидании'
    DIALING = 'dialing', 'Набирается'
    CONNECTING = 'connecting', 'Соединение'
    ANSWERED = 'answered', 'Отвечен'
    WAITING_RATING = 'waiting_rating', 'Ожидание оценки'
    WAITING_ADDITIONAL = 'waiting_additional', 'Ожидание дополнительной информации'
    TRANSFERRING = 'transferring', 'Перевод'
    COMPLETED = 'completed', 'Завершен успешно'
    NO_RATING = 'no_rating', 'Без оценки'
    TRANSFERRED = 'transferred', 'Переведен оператору'
    FAILED = 'failed', 'Неудачный вызов'


def validate_phone_number(value):
    """Validate phone number format"""
    if not value:
        raise ValidationError('Номер телефона обязателен для заполнения')

    # Remove spaces and special characters except + and digits
    phone_clean = re.sub(r'[^\d+]', '', str(value))

    # Basic phone number validation
    if not re.match(r'^\+?[1-9]\d{7,14}$', phone_clean):
        raise ValidationError(
            'Введите корректный номер телефона в международном формате '
            '(например: +998901234567)'
        )


class CallbackRequest(models.Model):
    phone_number = models.CharField(
        max_length=20,
        validators=[validate_phone_number],
        verbose_name="Номер телефона",
        help_text="Номер телефона в международном формате"
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        verbose_name="Бригада",
        help_text="Бригада экстренного реагирования"
    )
    status = models.CharField(
        max_length=20,
        choices=CallStatus.choices,
        default=CallStatus.PENDING,
        verbose_name="Статус вызова",
        help_text="Текущее состояние обратного вызова"
    )

    # Call details
    call_id = models.UUIDField(
        unique=True,
        null=True,
        blank=True,
        default=uuid.uuid4,
        verbose_name="ID вызова",
        help_text="Уникальный идентификатор вызова"
    )
    uniqueid = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Уникальный ID системы",
        help_text="Внутренний идентификатор телефонной системы"
    )
    channel = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Канал связи",
        help_text="Канал телефонной системы"
    )

    # Timing
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Время создания",
        help_text="Когда был создан запрос на обратный вызов"
    )
    call_started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Время начала звонка",
        help_text="Когда начался звонок"
    )
    call_ended_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Время окончания звонка",
        help_text="Когда закончился звонок"
    )
    call_duration = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Длительность вызова",
        help_text="Длительность вызова в секундах"
    )

    # Additional info
    error_message = models.TextField(
        null=True,
        blank=True,
        verbose_name="Сообщение об ошибке",
        help_text="Описание ошибки, если вызов не удался"
    )
    transferred = models.BooleanField(
        default=False,
        verbose_name="Переведен",
        help_text="Был ли вызов переведен оператору"
    )
    additional_questions = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="Дополнительные вопросы",
        help_text="Были ли заданы дополнительные вопросы"
    )

    # User who requested
    requested_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Кто запросил",
        help_text="Пользователь, который создал запрос на обратный вызов"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Запрос обратного вызова"
        verbose_name_plural = "Запросы обратного вызова"
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
            models.Index(fields=['phone_number']),
            models.Index(fields=['team']),
        ]

    def __str__(self):
        return f"Вызов на {self.phone_number} - {self.team.name} ({self.get_status_display()})"

    def clean(self):
        super().clean()

        # Validate phone number
        if self.phone_number:
            validate_phone_number(self.phone_number)

        # Validate team is active
        if self.team and not self.team.is_active:
            raise ValidationError({
                'team': 'Выбранная бригада неактивна. Выберите активную бригаду.'
            })

        # Validate call duration
        if self.call_duration is not None and self.call_duration < 0:
            raise ValidationError({
                'call_duration': 'Длительность вызова не может быть отрицательной'
            })

        # Validate time consistency
        if self.call_started_at and self.call_ended_at:
            if self.call_started_at > self.call_ended_at:
                raise ValidationError({
                    'call_ended_at': 'Время окончания не может быть раньше времени начала'
                })

    def save(self, *args, **kwargs):
        self.full_clean()

        # Auto-generate call_id if not set
        if not self.call_id:
            self.call_id = uuid.uuid4()

        # Calculate duration if both times are set
        if self.call_started_at and self.call_ended_at and not self.call_duration:
            duration = (self.call_ended_at - self.call_started_at).total_seconds()
            self.call_duration = int(duration)

        super().save(*args, **kwargs)

    @property
    def has_rating(self):
        """Check if this callback has a rating"""
        return hasattr(self, 'rating')

    @property
    def is_successful(self):
        """Check if the call was considered successful"""
        return self.status in [
            CallStatus.COMPLETED,
            CallStatus.TRANSFERRED
        ]

    @property
    def is_answered(self):
        """Check if the call was answered"""
        return self.status not in [
            CallStatus.PENDING,
            CallStatus.DIALING,
            CallStatus.CONNECTING,
            CallStatus.FAILED
        ]

    @property
    def is_active(self):
        """Check if the call is currently active/in progress"""
        return self.status in [
            CallStatus.PENDING,
            CallStatus.DIALING,
            CallStatus.CONNECTING,
            CallStatus.ANSWERED,
            CallStatus.WAITING_RATING,
            CallStatus.WAITING_ADDITIONAL,
            CallStatus.TRANSFERRING
        ]

    @property
    def status_color(self):
        """Get color class for status display"""
        status_colors = {
            CallStatus.PENDING: 'warning',
            CallStatus.DIALING: 'info',
            CallStatus.CONNECTING: 'info',
            CallStatus.ANSWERED: 'info',
            CallStatus.WAITING_RATING: 'info',
            CallStatus.WAITING_ADDITIONAL: 'info',
            CallStatus.TRANSFERRING: 'info',
            CallStatus.COMPLETED: 'success',
            CallStatus.TRANSFERRED: 'success',
            CallStatus.NO_RATING: 'warning',
            CallStatus.FAILED: 'danger',
        }
        return status_colors.get(self.status, 'secondary')

    @property
    def duration_formatted(self):
        """Get formatted duration string"""
        if not self.call_duration:
            return "—"

        hours = self.call_duration // 3600
        minutes = (self.call_duration % 3600) // 60
        seconds = self.call_duration % 60

        if hours > 0:
            return f"{hours}ч {minutes}м {seconds}с"
        elif minutes > 0:
            return f"{minutes}м {seconds}с"
        else:
            return f"{seconds}с"


class Rating(models.Model):
    RATING_CHOICES = [
        (1, '1 - Очень плохо'),
        (2, '2 - Плохо'),
        (3, '3 - Удовлетворительно'),
        (4, '4 - Хорошо'),
        (5, '5 - Отлично'),
    ]

    callback_request = models.OneToOneField(
        CallbackRequest,
        on_delete=models.CASCADE,
        related_name='rating',
        verbose_name="Запрос обратного вызова",
        help_text="Связанный запрос обратного вызова"
    )
    rating = models.IntegerField(
        choices=RATING_CHOICES,
        verbose_name="Оценка",
        help_text="Оценка качества обслуживания от 1 до 5"
    )
    comment = models.TextField(
        blank=True,
        null=True,
        max_length=500,
        verbose_name="Комментарий",
        help_text="Дополнительный комментарий к оценке (необязательно)"
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Время оценки",
        help_text="Когда была поставлена оценка"
    )

    # Additional data for analysis - denormalized for performance
    phone_number = models.CharField(
        max_length=20,
        verbose_name="Номер телефона",
        help_text="Номер телефона (копия для анализа)"
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        verbose_name="Бригада",
        help_text="Бригада (копия для анализа)"
    )
    date = models.DateField(
        auto_now_add=True,
        verbose_name="Дата оценки",
        help_text="Дата постановки оценки"
    )

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "Оценка вызова"
        verbose_name_plural = "Оценки вызовов"
        indexes = [
            models.Index(fields=['rating']),
            models.Index(fields=['date']),
            models.Index(fields=['team']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"{self.rating} звезд - {self.team.name} - {self.phone_number}"

    def clean(self):
        super().clean()

        # Validate rating value
        if self.rating is not None and (self.rating < 1 or self.rating > 5):
            raise ValidationError({
                'rating': 'Оценка должна быть от 1 до 5'
            })

        # Validate comment length
        if self.comment and len(self.comment) > 500:
            raise ValidationError({
                'comment': 'Комментарий не должен превышать 500 символов'
            })

    def save(self, *args, **kwargs):
        self.full_clean()

        # Auto-populate denormalized fields
        if self.callback_request:
            self.phone_number = self.callback_request.phone_number
            self.team = self.callback_request.team

        super().save(*args, **kwargs)

    @property
    def rating_text(self):
        """Get human-readable rating text"""
        rating_texts = {
            1: 'Очень плохо',
            2: 'Плохо',
            3: 'Удовлетворительно',
            4: 'Хорошо',
            5: 'Отлично'
        }
        return rating_texts.get(self.rating, 'Неизвестно')

    @property
    def rating_stars(self):
        """Get star representation of rating"""
        if not self.rating:
            return "☆☆☆☆☆"

        full_stars = "★" * self.rating
        empty_stars = "☆" * (5 - self.rating)
        return full_stars + empty_stars

    @property
    def rating_color(self):
        """Get color class for rating display"""
        if self.rating >= 4:
            return 'success'
        elif self.rating == 3:
            return 'warning'
        else:
            return 'danger'

    @property
    def is_positive(self):
        """Check if rating is positive (4-5 stars)"""
        return self.rating >= 4

    @property
    def is_negative(self):
        """Check if rating is negative (1-2 stars)"""
        return self.rating <= 2