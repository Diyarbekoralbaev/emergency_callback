import os
import django
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from teams.models import Team
from callbacks.models import CallbackRequest, Rating, CallStatus

User = get_user_model()


class Command(BaseCommand):
    help = 'Create test data for the ambulance callback system'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Creating test data...'))

        # Create superuser if doesn't exist
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
            self.stdout.write(self.style.SUCCESS('Created superuser: admin/admin123'))

        # Create test user
        if not User.objects.filter(username='operator').exists():
            User.objects.create_user('operator', 'operator@example.com', 'operator123')
            self.stdout.write(self.style.SUCCESS('Created test user: operator/operator123'))

        # Get users
        admin_user = User.objects.get(username='admin')
        operator_user = User.objects.get(username='operator')

        # Create test teams
        teams_data = [
            {'name': 'Emergency Team Alpha', 'description': 'Primary emergency response team'},
            {'name': 'Emergency Team Bravo', 'description': 'Secondary emergency response team'},
            {'name': 'Emergency Team Charlie', 'description': 'Backup emergency response team'},
            {'name': 'Trauma Unit', 'description': 'Specialized trauma response unit'},
            {'name': 'Cardiac Unit', 'description': 'Cardiac emergency specialists'},
        ]

        for team_data in teams_data:
            team, created = Team.objects.get_or_create(
                name=team_data['name'],
                defaults={
                    'description': team_data['description'],
                    'created_by': admin_user
                }
            )
            if created:
                self.stdout.write(f'Created team: {team.name}')

        # Create test callback requests
        test_phones = [
            '998901234567',
            '998907654321',
            '998912345678',
            '998987654321',
            '998923456789'
        ]

        teams = Team.objects.all()

        for i, phone in enumerate(test_phones):
            team = teams[i % len(teams)]

            # Create some completed requests with ratings
            if i < 3:
                callback = CallbackRequest.objects.create(
                    phone_number=phone,
                    team=team,
                    status=CallStatus.COMPLETED,
                    requested_by=operator_user
                )

                # Add rating
                rating_value = (i % 5) + 1  # Ratings 1-5
                Rating.objects.create(
                    callback_request=callback,
                    rating=rating_value,
                    phone_number=phone,
                    team=team
                )

                self.stdout.write(f'Created completed callback with {rating_value} star rating: {phone}')

            # Create some pending requests
            else:
                status = CallStatus.PENDING if i % 2 == 0 else CallStatus.FAILED
                CallbackRequest.objects.create(
                    phone_number=phone,
                    team=team,
                    status=status,
                    requested_by=operator_user,
                    error_message='Test error message' if status == CallStatus.FAILED else None
                )

                self.stdout.write(f'Created {status} callback: {phone}')

        self.stdout.write(self.style.SUCCESS('Test data creation completed!'))
        self.stdout.write(self.style.SUCCESS('\nLogin credentials:'))
        self.stdout.write(self.style.SUCCESS('Admin: admin/admin123'))
        self.stdout.write(self.style.SUCCESS('Operator: operator/operator123'))
