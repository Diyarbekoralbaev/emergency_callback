# teams/management/commands/create_test_data.py
import os
import django
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from teams.models import Team, Region
from callbacks.models import CallbackRequest, Rating, CallStatus
import random
from datetime import datetime, timedelta
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = 'Create comprehensive test data for the ambulance callback system with regions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing test data before creating new data',
        )
        parser.add_argument(
            '--minimal',
            action='store_true',
            help='Create minimal test data (fewer records)',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Creating comprehensive test data...'))

        if options['clear']:
            self.clear_existing_data()

        # Create users
        admin_user, operator_user = self.create_users()

        # Create regions
        regions = self.create_regions(admin_user)

        # Create teams
        teams = self.create_teams(regions, admin_user)

        # Create callback requests and ratings
        self.create_callbacks_and_ratings(teams, operator_user, minimal=options['minimal'])

        self.stdout.write(self.style.SUCCESS('\n' + '=' * 50))
        self.stdout.write(self.style.SUCCESS('TEST DATA CREATION COMPLETED!'))
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('\nLogin credentials:'))
        self.stdout.write(self.style.SUCCESS('🔑 Admin: admin/admin123'))
        self.stdout.write(self.style.SUCCESS('👤 Operator: operator/operator123'))
        self.stdout.write(self.style.SUCCESS('\nSystem Overview:'))
        self.stdout.write(self.style.SUCCESS(f'📍 Regions: {Region.objects.count()}'))
        self.stdout.write(self.style.SUCCESS(f'🚑 Teams: {Team.objects.count()}'))
        self.stdout.write(self.style.SUCCESS(f'📞 Callback Requests: {CallbackRequest.objects.count()}'))
        self.stdout.write(self.style.SUCCESS(f'⭐ Ratings: {Rating.objects.count()}'))

    def clear_existing_data(self):
        """Clear existing test data"""
        self.stdout.write(self.style.WARNING('Clearing existing test data...'))

        # Delete in correct order to avoid foreign key constraints
        Rating.objects.all().delete()
        CallbackRequest.objects.all().delete()
        Team.objects.all().delete()
        Region.objects.all().delete()

        # Delete test users (keep real users safe)
        User.objects.filter(username__in=['admin', 'operator']).delete()

        self.stdout.write(self.style.SUCCESS('✅ Existing test data cleared'))

    def create_users(self):
        """Create test users"""
        self.stdout.write(self.style.SUCCESS('\n👥 Creating users...'))

        # Create superuser if doesn't exist
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@example.com',
                'is_staff': True,
                'is_superuser': True
            }
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()
            self.stdout.write(self.style.SUCCESS('✅ Created superuser: admin/admin123'))
        else:
            self.stdout.write(self.style.WARNING('⚠️  Superuser already exists'))

        # Create test operator
        operator_user, created = User.objects.get_or_create(
            username='operator',
            defaults={
                'email': 'operator@example.com',
                'is_staff': False,
                'is_superuser': False
            }
        )
        if created:
            operator_user.set_password('operator123')
            operator_user.save()
            self.stdout.write(self.style.SUCCESS('✅ Created operator: operator/operator123'))
        else:
            self.stdout.write(self.style.WARNING('⚠️  Operator user already exists'))

        return admin_user, operator_user

    def create_regions(self, admin_user):
        """Create sample regions for Karakalpakstan"""
        self.stdout.write(self.style.SUCCESS('\n🗺️  Creating regions...'))

        regions_data = [
            {
                'name': 'Нукус',
                'code': 'NUK',
                'description': 'Столица Республики Каракалпакстан, центральный административный район с развитой медицинской инфраструктурой'
            },
            {
                'name': 'Ходжейли',
                'code': 'KHO',
                'description': 'Ходжейлийский район, северная часть республики с сельскохозяйственными предприятиями'
            },
            {
                'name': 'Чимбай',
                'code': 'CHI',
                'description': 'Чимбайский район, центральная часть республики с промышленными объектами'
            },
            {
                'name': 'Канлыкул',
                'code': 'KAN',
                'description': 'Канлыкульский район, восточная часть с преимущественно сельским населением'
            },
            {
                'name': 'Кегейли',
                'code': 'KEG',
                'description': 'Кегейлийский район, западная приграничная территория'
            },
            {
                'name': 'Кунград',
                'code': 'KUN',
                'description': 'Кунградский район, северо-западная часть с портовой инфраструктурой'
            },
            {
                'name': 'Турткуль',
                'code': 'TUR',
                'description': 'Турткульский район, южная часть с историческими памятниками'
            }
        ]

        regions = []
        for region_data in regions_data:
            region, created = Region.objects.get_or_create(
                code=region_data['code'],
                defaults={
                    'name': region_data['name'],
                    'description': region_data['description'],
                    'created_by': admin_user,
                    'is_active': True
                }
            )
            regions.append(region)

            if created:
                self.stdout.write(self.style.SUCCESS(f'✅ Created region: {region.name} ({region.code})'))
            else:
                self.stdout.write(self.style.WARNING(f'⚠️  Region already exists: {region.name}'))

        return regions

    def create_teams(self, regions, admin_user):
        """Create test teams distributed across regions"""
        self.stdout.write(self.style.SUCCESS('\n🚑 Creating emergency teams...'))

        teams_templates = [
            {
                'name_template': 'Экстренная бригада Альфа',
                'description': 'Основная экстренная бригада общего профиля с полным оснащением'
            },
            {
                'name_template': 'Травматологическая бригада',
                'description': 'Специализированная бригада по оказанию травматологической помощи'
            },
            {
                'name_template': 'Кардиологическая бригада',
                'description': 'Специализированная кардиологическая бригада с ЭКГ-оборудованием'
            },
            {
                'name_template': 'Педиатрическая бригада',
                'description': 'Детская экстренная бригада с педиатрическим оборудованием'
            },
            {
                'name_template': 'Реанимационная бригада',
                'description': 'Бригада интенсивной терапии с аппаратурой жизнеобеспечения'
            },
            {
                'name_template': 'Бригада быстрого реагирования',
                'description': 'Мобильная бригада для экстренных случаев'
            }
        ]

        teams = []
        for i, region in enumerate(regions):
            # Each region gets 2-3 teams
            teams_per_region = 2 if i >= 4 else 3  # First 4 regions get 3 teams, others get 2

            for j in range(teams_per_region):
                template = teams_templates[j % len(teams_templates)]
                team_name = f"{template['name_template']} - {region.name}"

                team, created = Team.objects.get_or_create(
                    name=team_name,
                    region=region,
                    defaults={
                        'description': template['description'],
                        'created_by': admin_user,
                        'is_active': True
                    }
                )
                teams.append(team)

                if created:
                    self.stdout.write(self.style.SUCCESS(f'✅ Created team: {team.name}'))
                else:
                    self.stdout.write(self.style.WARNING(f'⚠️  Team already exists: {team.name}'))

        return teams

    def create_callbacks_and_ratings(self, teams, operator_user, minimal=False):
        """Create callback requests and ratings"""
        self.stdout.write(self.style.SUCCESS('\n📞 Creating callback requests and ratings...'))

        # Sample phone numbers (Uzbekistan format)
        phone_numbers = [
            '998901234567', '998907654321', '998912345678', '998987654321',
            '998923456789', '998934567890', '998945678901', '998956789012',
            '998967890123', '998978901234', '998989012345', '998990123456',
            '998911111111', '998922222222', '998933333333', '998944444444',
            '998955555555', '998966666666', '998977777777', '998988888888'
        ]

        # Reduce data for minimal mode
        if minimal:
            phone_numbers = phone_numbers[:8]

        callbacks_created = 0
        ratings_created = 0

        for i, phone in enumerate(phone_numbers):
            team = teams[i % len(teams)]

            # Create callback with varied creation times (last 30 days)
            days_ago = random.randint(0, 30)
            hours_ago = random.randint(0, 23)
            minutes_ago = random.randint(0, 59)

            created_time = timezone.now() - timedelta(
                days=days_ago,
                hours=hours_ago,
                minutes=minutes_ago
            )

            # Determine status based on index for variety
            if i % 4 == 0:  # 25% failed
                status = CallStatus.FAILED
                error_message = random.choice([
                    'Номер недоступен',
                    'Отклонен пользователем',
                    'Технические неполадки',
                    'Превышено время ожидания'
                ])
            elif i % 4 == 1:  # 25% pending
                status = CallStatus.PENDING
                error_message = None
            elif i % 8 == 2:  # ~12.5% dialing
                status = CallStatus.DIALING
                error_message = None
            else:  # Rest completed
                status = CallStatus.COMPLETED
                error_message = None

            # Create callback request
            callback = CallbackRequest.objects.create(
                phone_number=phone,
                team=team,
                status=status,
                requested_by=operator_user,
                error_message=error_message,
                created_at=created_time
            )
            callbacks_created += 1

            # Create ratings for completed calls (80% chance)
            if status == CallStatus.COMPLETED and random.random() < 0.8:
                # Bias towards higher ratings (more realistic)
                rating_weights = [5, 15, 20, 35, 25]  # 1-5 stars distribution
                rating_value = random.choices(range(1, 6), weights=rating_weights)[0]

                # Optional comment for lower ratings
                comment = None
                if rating_value <= 2:
                    comments = [
                        'Долго ждали ответа',
                        'Не очень вежливый персонал',
                        'Качество связи было плохое'
                    ]
                    comment = random.choice(comments)
                elif rating_value >= 4:
                    comments = [
                        'Быстрый и профессиональный сервис!',
                        'Очень помогли, спасибо!',
                        'Отличная работа бригады',
                        'Все прошло хорошо'
                    ]
                    comment = random.choice(comments) if random.random() < 0.3 else None

                Rating.objects.create(
                    callback_request=callback,
                    rating=rating_value,
                    phone_number=phone,
                    team=team,
                    timestamp=created_time + timedelta(minutes=random.randint(5, 60))
                )
                ratings_created += 1

        self.stdout.write(self.style.SUCCESS(f'✅ Created {callbacks_created} callback requests'))
        self.stdout.write(self.style.SUCCESS(f'✅ Created {ratings_created} ratings'))

        # Create some recent activity (today)
        self.create_recent_activity(teams, operator_user)

    def create_recent_activity(self, teams, operator_user):
        """Create some recent callback activity for today"""
        self.stdout.write(self.style.SUCCESS('\n⏰ Creating recent activity...'))

        recent_phones = ['998901111111', '998902222222', '998903333333']

        for i, phone in enumerate(recent_phones):
            team = random.choice(teams)

            # Recent callbacks (today)
            hours_ago = random.randint(1, 8)
            created_time = timezone.now() - timedelta(hours=hours_ago)

            status = CallStatus.COMPLETED if i < 2 else CallStatus.PENDING

            callback = CallbackRequest.objects.create(
                phone_number=phone,
                team=team,
                status=status,
                requested_by=operator_user,
                created_at=created_time
            )

            if status == CallStatus.COMPLETED:
                Rating.objects.create(
                    callback_request=callback,
                    rating=random.randint(4, 5),
                    phone_number=phone,
                    team=team,
                    timestamp=created_time + timedelta(minutes=30)
                )

        self.stdout.write(self.style.SUCCESS('✅ Created recent activity for today'))