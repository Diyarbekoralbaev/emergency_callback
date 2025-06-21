#callbacks/models.py
from django.db import models
from users.models import User
from teams.models import Team


class CallStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    DIALING = 'dialing', 'Dialing'
    CONNECTING = 'connecting', 'Connecting'
    ANSWERED = 'answered', 'Answered'
    WAITING_RATING = 'waiting_rating', 'Waiting Rating'
    WAITING_ADDITIONAL = 'waiting_additional', 'Waiting Additional'
    TRANSFERRING = 'transferring', 'Transferring'
    COMPLETED = 'completed', 'Completed'  # Successfully completed (with or without rating)
    NO_RATING = 'no_rating', 'No Rating Given'  # Answered but hung up without rating
    TRANSFERRED = 'transferred', 'Transferred'  # Transferred to operator
    FAILED = 'failed', 'Failed'  # Never answered or technical failure


class CallbackRequest(models.Model):
    phone_number = models.CharField(max_length=20)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=CallStatus.choices, default=CallStatus.PENDING)

    # Call details
    call_id = models.UUIDField(unique=True, null=True, blank=True)
    uniqueid = models.CharField(max_length=100, null=True, blank=True)
    channel = models.CharField(max_length=100, null=True, blank=True)

    # Timing
    created_at = models.DateTimeField(auto_now_add=True)
    call_started_at = models.DateTimeField(null=True, blank=True)
    call_ended_at = models.DateTimeField(null=True, blank=True)
    call_duration = models.IntegerField(null=True, blank=True, help_text="Duration in seconds")

    # Additional info
    error_message = models.TextField(null=True, blank=True)
    transferred = models.BooleanField(default=False)
    additional_questions = models.BooleanField(null=True, blank=True)

    # User who requested
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return f"Call to {self.phone_number} - {self.team.name} ({self.status})"

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

    class Meta:
        ordering = ['-created_at']


class Rating(models.Model):
    RATING_CHOICES = [
        (1, '1 Star'),
        (2, '2 Stars'),
        (3, '3 Stars'),
        (4, '4 Stars'),
        (5, '5 Stars'),
    ]

    callback_request = models.OneToOneField(CallbackRequest, on_delete=models.CASCADE)
    rating = models.IntegerField(choices=RATING_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)

    # Additional data for analysis
    phone_number = models.CharField(max_length=20)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.rating} stars - {self.team.name} - {self.phone_number}"

    @property
    def rating_text(self):
        """Get human-readable rating text"""
        rating_texts = {
            1: 'Very Poor',
            2: 'Poor',
            3: 'Average',
            4: 'Good',
            5: 'Excellent'
        }
        return rating_texts.get(self.rating, 'Unknown')

    @property
    def rating_color(self):
        """Get color class for rating display"""
        if self.rating >= 4:
            return 'success'
        elif self.rating == 3:
            return 'warning'
        else:
            return 'danger'

    class Meta:
        ordering = ['-timestamp']