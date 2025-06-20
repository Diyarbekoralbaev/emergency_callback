from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """
    Custom user model that extends Django's AbstractUser.
    This allows for future extensibility without changing the default user model.
    """
    # Additional fields can be added here if needed in the future
    pass

    def __str__(self):
        return f"{self.username} ({self.id})"