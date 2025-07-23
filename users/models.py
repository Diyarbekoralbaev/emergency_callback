from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRoleChoices(models.TextChoices):
    ADMIN = 'admin', 'Admin'
    OPERATOR = 'operator', 'Operator'

    @classmethod
    def get_choices(cls):
        return [(choice.value, choice.label) for choice in cls]

    @classmethod
    def is_valid_role(cls, role):
        return role in [choice.value for choice in cls]

class User(AbstractUser):
    """
    Custom user model that extends Django's AbstractUser.
    This allows for future extensibility without changing the default user model.
    """
    role = models.CharField(
        max_length=20,
        choices=UserRoleChoices.get_choices(),
        default=UserRoleChoices.OPERATOR,
        help_text="User's role in the system"
    )

    def __str__(self):
        return f"{self.username} ({self.id})"