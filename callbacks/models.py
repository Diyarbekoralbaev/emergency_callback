from django.db import models
from users.models import User
from teams.models import Team


class CallStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    DIALING = 'dialing', 'Dialing'
    CONNECTING = 'connecting', 'Connecting'
    ANSWERED = 'answered', 'Answered'
    WAITING_RATING = 'waiting_rating', 'Waiting Rating'
    RATING_RECEIVED = 'rating_received', 'Rating Received'
    WAITING_ADDITIONAL = 'waiting_additional', 'Waiting Additional'
    TRANSFERRING = 'transferring', 'Transferring'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'


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

    # Additional info
    error_message = models.TextField(null=True, blank=True)
    transferred = models.BooleanField(default=False)
    additional_questions = models.BooleanField(null=True, blank=True)

    # User who requested
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return f"Call to {self.phone_number} - {self.team.name} ({self.status})"

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

    class Meta:
        ordering = ['-timestamp']