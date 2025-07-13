# teams/management/commands/create_real_data.py
import csv
import os
import django
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from teams.models import Team, Region
from django.utils.text import slugify
import re

User = get_user_model()


class Command(BaseCommand):
    help = 'Create real data from CSV file for the ambulance callback system'

    def add_arguments(self, parser):
        parser.add_argument(
            'csv_file',
            type=str,
            help='Path to the CSV file containing real brigade data'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing data before creating new data',
        )
        parser.add_argument(
            '--update',
            action='store_true',
            help='Update existing data instead of creating new',
        )

    def handle(self, *args, **options):
        csv_file_path = options['csv_file']

        if not os.path.exists(csv_file_path):
            self.stdout.write(
                self.style.ERROR(f'CSV file not found: {csv_file_path}')
            )
            return

        self.stdout.write(self.style.SUCCESS('Creating real data from CSV...'))

        if options['clear']:
            self.clear_existing_data()

        # Get or create admin user
        admin_user = self.get_or_create_admin_user()

        # Parse CSV and create data
        regions_data, teams_data = self.parse_csv(csv_file_path)

        # Create regions first
        regions_map = self.create_regions(regions_data, admin_user, options['update'])

        # Create teams
        self.create_teams(teams_data, regions_map, admin_user, options['update'])

        self.stdout.write(self.style.SUCCESS('\n' + '=' * 50))
        self.stdout.write(self.style.SUCCESS('REAL DATA CREATION COMPLETED!'))
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('\nSystem Overview:'))
        self.stdout.write(self.style.SUCCESS(f'📍 Regions: {Region.objects.count()}'))
        self.stdout.write(self.style.SUCCESS(f'🚑 Teams: {Team.objects.count()}'))

    def clear_existing_data(self):
        """Clear existing data"""
        self.stdout.write(self.style.WARNING('Clearing existing data...'))
        Team.objects.all().delete()
        Region.objects.all().delete()
        self.stdout.write(self.style.SUCCESS('✅ Existing data cleared'))

    def get_or_create_admin_user(self):
        """Get or create admin user"""
        try:
            # Try to get existing superuser
            admin_user = User.objects.filter(is_superuser=True).first()
            if admin_user:
                return admin_user

            # Create admin user if none exists
            admin_user = User.objects.create_user(
                username='admin',
                email='admin@example.com',
                password='admin123',
                is_staff=True,
                is_superuser=True
            )
            self.stdout.write(self.style.SUCCESS('✅ Created admin user'))
            return admin_user

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error creating admin user: {e}'))
            raise

    def parse_csv(self, csv_file_path):
        """Parse CSV file and extract regions and teams data"""
        self.stdout.write(self.style.SUCCESS('📄 Parsing CSV file...'))

        regions_data = {}
        teams_data = []

        try:
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                csv_reader = csv.DictReader(file)

                for row_num, row in enumerate(csv_reader, start=2):
                    region_name = row['region'].strip()
                    brigade_name = row['brigada'].strip()
                    comment = row['comment'].strip()

                    if not region_name or not brigade_name:
                        self.stdout.write(
                            self.style.WARNING(f'⚠️  Skipping empty row {row_num}')
                        )
                        continue

                    # Collect unique regions
                    if region_name not in regions_data:
                        regions_data[region_name] = {
                            'name': region_name,
                            'code': self.generate_region_code(region_name),
                            'description': self.generate_region_description(region_name, comment)
                        }

                    # Collect teams data
                    teams_data.append({
                        'name': brigade_name,
                        'region_name': region_name,
                        'description': self.generate_team_description(brigade_name, comment),
                        'comment': comment
                    })

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error parsing CSV: {e}'))
            raise

        self.stdout.write(
            self.style.SUCCESS(f'✅ Parsed {len(regions_data)} regions and {len(teams_data)} teams')
        )

        # Debug: Show all regions that will be created
        self.stdout.write(self.style.SUCCESS('\n📋 Regions to be created:'))
        for region_name, region_info in regions_data.items():
            brigade_count = len([t for t in teams_data if t['region_name'] == region_name])
            self.stdout.write(
                self.style.SUCCESS(f'   • {region_name} ({region_info["code"]}) - {brigade_count} brigades')
            )

        return regions_data, teams_data

    def generate_region_code(self, region_name):
        """Generate a region code from region name"""
        # Exact mapping for specific region names to avoid conflicts
        exact_mapping = {
            'Nukus city': 'NUK',
            'Нукус район': 'NUR',  # Different code for район
            'Элликкала': 'ELL',
            'Ходжейли': 'KHO',
            'Бозатау': 'BOZ',
            'Тахиаташ': 'TAH',
            'Тахтакупир': 'TAK',
            'Шымбай': 'SHY',
            'Шоманай': 'SHO',
            'Беруний': 'BER',
            'Караозек': 'KAR',
            'Мойнак': 'MOY',
            'Канлыкуль': 'KAN',
            'Кегейли': 'KEG',
            'Конырат': 'KON',
            'Турткуль': 'TUR',
            'Амударья': 'AMU'
        }

        # Check exact match first
        if region_name in exact_mapping:
            return exact_mapping[region_name]

        # Fallback: create code from name
        clean_name = re.sub(r'(город|city|район|область)', '', region_name, flags=re.IGNORECASE)
        clean_name = clean_name.strip()

        # Use first 3 characters, handling Cyrillic
        return clean_name[:3].upper()

    def generate_region_description(self, region_name, comment):
        """Generate description for region"""
        base_descriptions = {
            'центр': 'Центральный административный район с развитой медицинской инфраструктурой',
            'район': 'Районный центр с сетью медицинских учреждений',
            'подстанция': 'Подстанция экстренной медицинской помощи'
        }

        description = base_descriptions.get(comment, 'Территориальная единица системы экстренной медицинской помощи')

        if 'city' in region_name.lower() or 'город' in region_name.lower():
            return f"Городской округ {region_name} - {description}"
        else:
            return f"{region_name} - {description}"

    def generate_team_description(self, brigade_name, comment):
        """Generate description for team based on brigade type"""
        brigade_types = {
            'РСБ': 'Реанимационно-специализированная бригада с оборудованием интенсивной терапии',
            'ПСБ': 'Педиатрическая специализированная бригада для оказания помощи детям',
            'ОПВ': 'Общепрофильная выездная бригада скорой медицинской помощи',
            'ОПФ': 'Общепрофильная фельдшерская бригада скорой медицинской помощи',
            'СПЕЦ': 'Специализированная бригада для сложных случаев',
            'ОПБ': 'Общепрофильная бригада скорой медицинской помощи'
        }

        # Extract brigade type from name
        for brigade_type, description in brigade_types.items():
            if brigade_type in brigade_name:
                location_desc = {
                    'центр': 'центральной больницы',
                    'район': 'районной больницы',
                    'подстанция': 'подстанции скорой помощи'
                }.get(comment, 'медицинского учреждения')

                return f"{description} {location_desc}"

        # Check for numbered brigades
        if 'Бригада' in brigade_name:
            return f"Выездная бригада скорой медицинской помощи"

        return "Бригада экстренной медицинской помощи"

    def create_regions(self, regions_data, admin_user, update_mode=False):
        """Create or update regions"""
        self.stdout.write(self.style.SUCCESS('\n🗺️  Creating regions...'))

        regions_map = {}
        created_count = 0
        updated_count = 0

        for region_name, region_info in regions_data.items():
            try:
                region, created = Region.objects.get_or_create(
                    code=region_info['code'],
                    defaults={
                        'name': region_info['name'],
                        'description': region_info['description'],
                        'created_by': admin_user,
                        'is_active': True
                    }
                )

                if not created and update_mode:
                    # Update existing region
                    region.name = region_info['name']
                    region.description = region_info['description']
                    region.save()
                    updated_count += 1
                    self.stdout.write(
                        self.style.WARNING(f'📝 Updated region: {region.name} ({region.code})')
                    )
                elif created:
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'✅ Created region: {region.name} ({region.code})')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f'⚠️  Region already exists: {region.name}')
                    )

                regions_map[region_name] = region

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'❌ Error creating region {region_name}: {e}')
                )

        if update_mode:
            self.stdout.write(
                self.style.SUCCESS(f'📍 Created {created_count} and updated {updated_count} regions')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'📍 Created {created_count} regions')
            )

        return regions_map

    def create_teams(self, teams_data, regions_map, admin_user, update_mode=False):
        """Create or update teams"""
        self.stdout.write(self.style.SUCCESS('\n🚑 Creating teams...'))

        created_count = 0
        updated_count = 0
        error_count = 0

        for team_info in teams_data:
            try:
                region = regions_map.get(team_info['region_name'])
                if not region:
                    self.stdout.write(
                        self.style.ERROR(f'❌ Region not found for team: {team_info["name"]}')
                    )
                    error_count += 1
                    continue

                # Create unique team name if duplicate exists
                team_name = team_info['name']
                base_name = team_name
                counter = 1

                while Team.objects.filter(name=team_name, region=region).exists():
                    if update_mode:
                        # Update existing team
                        team = Team.objects.get(name=team_name, region=region)
                        team.description = team_info['description']
                        team.save()
                        updated_count += 1
                        self.stdout.write(
                            self.style.WARNING(f'📝 Updated team: {team.name} - {region.name}')
                        )
                        break
                    else:
                        counter += 1
                        team_name = f"{base_name} #{counter}"
                else:
                    # Create new team
                    team = Team.objects.create(
                        name=team_name,
                        region=region,
                        description=team_info['description'],
                        created_by=admin_user,
                        is_active=True
                    )
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'✅ Created team: {team.name} - {region.name}')
                    )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'❌ Error creating team {team_info["name"]}: {e}')
                )
                error_count += 1

        if update_mode:
            self.stdout.write(
                self.style.SUCCESS(f'🚑 Created {created_count} and updated {updated_count} teams')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'🚑 Created {created_count} teams')
            )

        if error_count > 0:
            self.stdout.write(
                self.style.WARNING(f'⚠️  {error_count} teams had errors')
            )